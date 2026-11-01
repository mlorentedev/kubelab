"""Check that the uplink's shaper keeps a lab Wi-Fi client usable under bulk load (NET-005 B9, AC8).

AC8: with the uplink shaped both ways, neither a bulk download nor a bulk upload
from a homelab host starves a lab Wi-Fi client. The client's TCP connect time is
measured under each load, with and without the shaper, and the bound is recorded.

Three hosts take part, each reached on the path that does not cross the load:

- The load runs on bee, a homelab host behind the edge, over the LAN. Its streams
  are `edge_measure`'s: the same server, request size and back-off.
- The client is rpi3, the one always-present lab Wi-Fi client. The switch cannot
  reach it, so it is reached over the tailnet, which rides the uplink. The probe
  runs detached into a file and is collected after the window, so a saturated
  link loses no samples.
- The edge's uplink counters are read around each window, over the LAN, to say
  which direction the load took and that it crossed the uplink at all.

The shaper is lifted by stopping its unit, whose ExecStop deletes its qdiscs, and
restored by starting it. The restore always runs, is retried once, and is read
back: a CAKE root qdisc on the uplink and the unit active. A restore that cannot
be read back fails the run, whatever the measurements say.
"""

from __future__ import annotations

import statistics
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from toolkit.features.edge_measure import DOWN_URL, STREAMS, UP_BYTES, UP_URL
from toolkit.features.edge_status import _ssh
from toolkit.features.k8s_connect import resolve_ssh_user

SHAPER_UNIT = "kubelab-edge-shaper.service"
WINDOW_S = 30
# A one-byte answer: the probe times the connect, not a transfer.
PROBE_URL = "https://speed.cloudflare.com/__down?bytes=0"
PROBE_FILE = "/tmp/kubelab-shape-probe"
SESSION_TIMEOUT_S = 90
LOAD_HOST, CLIENT_HOST = "beelink", "rpi3"
# A load window is a reading only if the uplink carried at least this much in the
# load's direction. curl's `000` cannot tell a request cut at the window's end
# from one that never connected, so the counters decide whether the load ran.
MIN_LOAD_MBIT = 1.0

# Run in this order: the shaped windows first, so the shaper is lifted for the
# shortest time.
WINDOWS = (
    ("idle", None, True),
    ("download, shaped", "down", True),
    ("upload, shaped", "up", True),
    ("download, unshaped", "down", False),
    ("upload, unshaped", "up", False),
)

Run = Callable[[list[str], str], tuple[int, str]]


def _host_ssh(networking: dict[str, Any], name: str, via: str) -> list[str]:
    node = networking["nodes"][name]
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        # The workstation pins every node's key under its tailnet address.
        "-o",
        f"HostKeyAlias={node['tailscale_ip']}",
        f"{resolve_ssh_user(networking, name)}@{node['tailscale_ip' if via == 'tailnet' else 'lan_ip']}",
    ]


def load_script(direction: str, seconds: int = WINDOW_S, streams: int = STREAMS) -> str:
    """bee's streams for one window. Each request prints `code <status>`."""
    if direction == "down":
        request = f'curl -s -o /dev/null -m $(( end - $(date +%s) + 1 )) -w "%{{http_code}}" "{DOWN_URL}"'
    else:
        request = (
            f"head -c {UP_BYTES} /dev/zero | curl -s -o /dev/null -m $(( end - $(date +%s) + 1 ))"
            f' -w "%{{http_code}}" -H "Expect:" --data-binary @- "{UP_URL}"'
        )
    loop = (
        f'end=$(( $(date +%s) + {seconds} )); while [ "$(date +%s)" -lt "$end" ]; do'
        f' c=$({request}); echo "code $c"; case "$c" in 2*|000) ;; *) sleep 2 ;; esac; done'
    )
    return f"for i in $(seq {streams}); do ( {loop} ) & done; wait"


def probe_start_script(seconds: int = WINDOW_S) -> str:
    """rpi3's probe, detached: one connect a second into a file, for the window."""
    loop = (
        f'end=$(( $(date +%s) + {seconds} )); while [ "$(date +%s)" -lt "$end" ]; do'
        f' curl -4 -s -o /dev/null --connect-timeout 5 -m 8 -w "%{{time_connect}} %{{http_code}}\\n" "{PROBE_URL}";'
        " sleep 1; done"
    )
    return f"rm -f {PROBE_FILE}; nohup sh -c '{loop}' >{PROBE_FILE} 2>/dev/null </dev/null & echo started"


def probe_collect_script() -> str:
    return f"cat {PROBE_FILE} 2>/dev/null; rm -f {PROBE_FILE}"


def counters_script(interface: str) -> str:
    """The uplink adapter's counters, read before the shaper's IFB."""
    stats = f"/sys/class/net/{interface}/statistics"
    return f'printf "rx=%s tx=%s t=%s\\n" $(cat {stats}/rx_bytes {stats}/tx_bytes) "$(date +%s.%N)"'


def shaper_script(action: str, interface: str) -> str:
    """Stop or start the shaper, then read back whether CAKE shapes the uplink."""
    return (
        f"sudo -n systemctl {action} {SHAPER_UNIT};"
        f' printf "unit %s\\n" "$(systemctl is-active {SHAPER_UNIT})";'
        f' tc qdisc show dev {interface} root | grep -q " cake " && echo "cake yes" || echo "cake no"'
    )


def _facts(output: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for line in output.splitlines():
        key, _, value = line.partition(" ")
        facts[key] = value.strip()
    return facts


def _counters(output: str) -> dict[str, float] | None:
    try:
        return {k: float(v) for k, v in (part.split("=", 1) for part in output.split())}
    except ValueError:
        return None


@dataclass
class Window:
    """One window's load, the edge's counters around it and the client's samples."""

    name: str
    direction: str | None
    shaped: bool
    answered: int = 0
    cut: int = 0
    refused: int = 0
    down_mbit: float | None = None
    up_mbit: float | None = None
    connects_ms: list[float] = field(default_factory=list)
    failures: int = 0
    unreadable: str = ""

    def summary(self) -> str:
        if self.unreadable:
            return f"{self.name}: cannot tell ({self.unreadable})"
        rates = (
            f"uplink {self.down_mbit:.1f} down / {self.up_mbit:.1f} up Mbit/s"
            if self.down_mbit is not None and self.up_mbit is not None
            else "uplink rate unread"
        )
        load = f", load answered {self.answered} cut {self.cut} refused {self.refused}" if self.direction else ""
        if not self.connects_ms:
            return f"{self.name}: {rates}{load}; no connect succeeded, {self.failures} failed"
        ordered = sorted(self.connects_ms)
        return (
            f"{self.name}: {rates}{load}; connect p50 {statistics.median(ordered):.0f} ms,"
            f" p95 {self.p95():.0f} ms, max {ordered[-1]:.0f} ms over {len(ordered)}, {self.failures} failed"
        )

    def p95(self) -> float | None:
        if not self.connects_ms:
            return None
        ordered = sorted(self.connects_ms)
        return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def read_probe(output: str, window: Window) -> None:
    """`<time_connect s> <http_code>` per line; a code of 000 is a failed connect."""
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        seconds, code = parts
        if code == "000":
            window.failures += 1
        else:
            try:
                window.connects_ms.append(float(seconds) * 1000)
            except ValueError:
                window.failures += 1


def read_load(output: str, window: Window) -> None:
    """A 2xx was answered; 000 is a request still running when the window ended,
    as `edge_measure` reads it; anything else the server refused."""
    for line in output.splitlines():
        if line.startswith("code "):
            status = line.removeprefix("code ")
            if status.startswith("2"):
                window.answered += 1
            elif status == "000":
                window.cut += 1
            else:
                window.refused += 1


def _run(command: list[str], script: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [*command, script],
            check=False,
            stdout=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=SESSION_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return 255, ""
    return result.returncode, result.stdout


@dataclass
class Check:
    windows: list[Window] = field(default_factory=list)
    restored: bool = True
    restore_note: str = ""
    unreachable: str = ""


def _window(
    hosts: dict[str, list[str]],
    interface: str,
    spec: tuple[str, str | None, bool],
    run: Run,
    sleep: Callable[[float], None],
) -> Window:
    name, direction, shaped = spec
    window = Window(name, direction, shaped)
    _, before = run(hosts["edge"], counters_script(interface))
    code, out = run(hosts["client"], probe_start_script())
    if code != 0 or "started" not in out:
        window.unreadable = "the probe on rpi3 did not start"
        return window
    if direction:
        _, out = run(hosts["load"], load_script(direction))
        read_load(out, window)
    else:
        sleep(WINDOW_S)
    # Let the probe's last connect finish.
    sleep(2)
    _, after = run(hosts["edge"], counters_script(interface))
    _, out = run(hosts["client"], probe_collect_script())
    read_probe(out, window)
    start, end = _counters(before), _counters(after)
    if start and end and end["t"] > start["t"]:
        span = end["t"] - start["t"]
        window.down_mbit = (end["rx"] - start["rx"]) * 8 / span / 1e6
        window.up_mbit = (end["tx"] - start["tx"]) * 8 / span / 1e6
    carried = window.down_mbit if direction == "down" else window.up_mbit
    if direction and window.answered + window.cut == 0:
        window.unreadable = f"the server refused every load request ({window.refused} refused)"
    elif direction and (carried is None or carried < MIN_LOAD_MBIT):
        rate = "unread" if carried is None else f"{carried:.1f} Mbit/s"
        window.unreadable = f"the load did not cross the uplink ({direction} {rate})"
    elif not window.connects_ms and not window.failures:
        window.unreadable = "the probe on rpi3 recorded nothing"
    return window


def _set_shaper(hosts: dict[str, list[str]], interface: str, action: str, run: Run) -> dict[str, str]:
    _, out = run(hosts["edge"], shaper_script(action, interface))
    return _facts(out)


def run_shape_check(
    networking: dict[str, Any],
    bound_ms: float | None = None,
    run: Run = _run,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, list[str]]:
    """Measure the client's connect times under each load, with and without the shaper.

    0 measured (and within `bound_ms` when given), 1 a shaped window over the bound,
    3 cannot tell or the shaper not restored, 255 the edge did not answer."""
    interface = networking["edge"]["uplink"]["interface"]
    hosts = {
        "edge": _ssh(networking),
        "load": _host_ssh(networking, LOAD_HOST, "lan"),
        "client": _host_ssh(networking, CLIENT_HOST, "tailnet"),
    }
    check = Check()
    first = _set_shaper(hosts, interface, "start", run)
    if not first:
        return 255, ["verdict: the edge did not answer, nothing was run"]
    if first.get("cake") != "yes":
        return 3, ["verdict: cannot tell, the uplink is not shaped before the run, so there is no shaped window"]
    try:
        for spec in WINDOWS:
            if not spec[2] and check.windows and check.windows[-1].shaped:
                stopped = _set_shaper(hosts, interface, "stop", run)
                if stopped.get("cake") != "no":
                    check.unreachable = "the shaper did not come off, so the unshaped windows were not run"
                    break
            check.windows.append(_window(hosts, interface, spec, run, sleep))
    finally:
        for _ in range(2):
            restored = _set_shaper(hosts, interface, "start", run)
            if restored.get("cake") == "yes" and restored.get("unit") == "active":
                check.restored, check.restore_note = True, ""
                break
            check.restored = False
            check.restore_note = f"unit {restored.get('unit', 'unread')}, cake {restored.get('cake', 'unread')}"
    return _verdict(check, bound_ms)


def _verdict(check: Check, bound_ms: float | None) -> tuple[int, list[str]]:
    lines = [window.summary() for window in check.windows]
    if check.unreachable:
        lines.append(check.unreachable)
    if not check.restored:
        lines.append(
            f"verdict: SHAPER NOT RESTORED ({check.restore_note}): run `make provision NODE=rpi4 ENV=prod BOOTSTRAP=1"
            " TAGS=gateway` from the switch"
        )
        return 3, lines
    lines.append("shaper: restored, CAKE on the uplink")
    if check.unreachable or any(window.unreadable for window in check.windows):
        lines.append("verdict: cannot tell, a window has no reading")
        return 3, lines
    shaped = [w for w in check.windows if w.shaped and w.direction]
    # A connect lost under a shaped load is starvation, bound or not.
    lost = [w.name for w in shaped if w.failures]
    if lost:
        lines.append(f"verdict: FAILED, connects lost under a shaped load: {', '.join(lost)}")
        return 1, lines
    if bound_ms is not None:
        over = [w.name for w in shaped if (w.p95() or float("inf")) > bound_ms]
        if over:
            lines.append(f"verdict: FAILED, over {bound_ms:.0f} ms at p95: {', '.join(over)}")
            return 1, lines
        lines.append(f"verdict: within {bound_ms:.0f} ms at p95 under both shaped loads")
        return 0, lines
    lines.append("verdict: measured; record the bound in verification.md")
    return 0, lines
