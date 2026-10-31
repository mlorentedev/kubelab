"""Measure the lab edge's uplink line rate (NET-005 AC8, #2876).

`networking.edge.uplink.bandwidth` shapes the uplink a little below its measured
rate, so it has to be re-measured whenever the site or its plan changes. The
measurement runs on the edge itself and counts on the uplink adapter's own
`rx_bytes`/`tx_bytes`. Ingress is redirected to the IFB after those counters, so
they read the line, whoever in the lab uses it.

Three facts from the measurement that set the shaper in #2875 shape the reading:

- A shaper that binds hides the line: arrival sits at `down_kbit` while the IFB
  drops. A run that reaches 90% of a shaped rate with drops reports a lower bound
  and says to lift the shaper, never a line rate.
- Streams repeat a moderate request for the whole window, since one large request
  can end early. A refused request is reported and backs off; the run reads only
  if each direction got answers.
- The server rations large requests per address: after about fifteen minutes of
  six 25 MB streams it answered 429 to 10 MB and 25 MB requests while still
  serving 5 MB ones. Two runs per site change stay far below that, so the request
  stays at 25 MB, and a direction with no answered request reads as cannot tell.
  A second server is not a cross-check: one read 14 Mbit/s from the edge and a
  laptop alike, where this one read 27.
- Wi-Fi rates move with the hour. The report carries the time and the link's band
  and receive rate, so two readings can be compared.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any

from toolkit.features.edge_status import _edge, _ssh

STREAMS = 6
SECONDS = 60
# 90% of the lower of two readings (AC8): the queue then forms in the edge's CAKE.
SHAPE_RATIO = 0.9
DOWN_URL = "https://speed.cloudflare.com/__down?bytes=25000000"
UP_URL = "https://speed.cloudflare.com/__up"
UP_BYTES = 10_000_000
DIRECTIONS = ("down", "up")


def remote_command(interface: str, ifb: str, seconds: int = SECONDS, streams: int = STREAMS) -> str:
    """The POSIX shell the edge runs: its link, its shaper, then one window per direction.

    Each window prints the adapter's counters and the qdisc's drops before and after,
    and every HTTP status the streams got."""
    counters = (
        f'printf "%s rx=%s tx=%s drops_down=%s drops_up=%s t=%s\\n" "$1"'
        f" $(cat /sys/class/net/{interface}/statistics/rx_bytes /sys/class/net/{interface}/statistics/tx_bytes)"
        f' "$(tc -s qdisc show dev {ifb} | sed -n "s/.*dropped \\([0-9]*\\).*/\\1/p" | head -n1)"'
        f' "$(tc -s qdisc show dev {interface} root | sed -n "s/.*dropped \\([0-9]*\\).*/\\1/p" | head -n1)"'
        ' "$(date +%s.%N)"'
    )
    # A refused request backs off, so a stream the server rate-limits does not spin.
    stream = (
        'end=$(( $(date +%s) + {s} )); while [ "$(date +%s)" -lt "$end" ]; do'
        ' c=$({req}); echo "code {d} $c"; case "$c" in 2*|000) ;; *) sleep 2 ;; esac; done'
    )
    down = f'curl -s -o /dev/null -m $(( end - $(date +%s) + 1 )) -w "%{{http_code}}" "{DOWN_URL}"'
    up = (
        f"head -c {UP_BYTES} /dev/zero | curl -s -o /dev/null -m $(( end - $(date +%s) + 1 ))"
        f' -w "%{{http_code}}" -H "Expect:" --data-binary @- "{UP_URL}"'
    )
    lines = [
        f"stamp() {{ {counters}; }}",
        f'printf "link %s\\n" "$(iw dev {interface} link'
        ' | sed -n "s/^[[:space:]]*\\(freq\\|rx bitrate\\): //p" | tr "\\n" " ")"',
        f'printf "shaper down=%s up=%s\\n" "$(tc qdisc show dev {ifb} | sed -n "s/.*bandwidth \\([^ ]*\\).*/\\1/p")"'
        f' "$(tc qdisc show dev {interface} root | sed -n "s/.*bandwidth \\([^ ]*\\).*/\\1/p")"',
    ]
    for direction, request in (("down", down), ("up", up)):
        loop = stream.format(s=seconds, req=request, d=direction)
        lines += [
            f"stamp {direction}-start",
            f"for i in $(seq {streams}); do ( {loop} ) & done; wait",
            f"stamp {direction}-end",
        ]
    return "\n".join(lines)


def _kbit(value: str) -> float:
    """tc's rate as kbit/s: `24Mbit`, `3600Kbit`, or `unlimited`."""
    units = {"Gbit": 1_000_000, "Mbit": 1000, "Kbit": 1, "bit": 0.001}
    for unit, factor in units.items():
        if value.endswith(unit):
            return float(value[: -len(unit)]) * factor
    return 0.0


@dataclass
class Window:
    kbit: float = 0.0
    drops: int = 0
    answered: int = 0
    refused: list[str] = field(default_factory=list)


@dataclass
class Reading:
    link: str = ""
    shaper: dict[str, float] = field(default_factory=dict)
    windows: dict[str, Window] = field(default_factory=dict)
    unreadable: str = ""

    @property
    def binding(self) -> list[str]:
        """The directions whose shaper bound the window, so their rate is a lower bound."""
        return [
            d
            for d, w in self.windows.items()
            if w.drops > 0 and self.shaper.get(d, 0) and w.kbit >= SHAPE_RATIO * self.shaper[d]
        ]

    @property
    def code(self) -> int:
        """0 measured, 2 the shaper bound a window, 3 cannot be read."""
        if self.unreadable:
            return 3
        return 2 if self.binding else 0


def read(output: str) -> Reading:
    """Read what `remote_command` printed."""
    reading = Reading()
    stamps: dict[str, dict[str, float]] = {}
    codes: dict[str, list[str]] = {d: [] for d in DIRECTIONS}
    for line in output.splitlines():
        head, _, rest = line.partition(" ")
        if head == "link":
            reading.link = rest.strip()
        elif head == "shaper":
            values = dict(part.split("=", 1) for part in rest.split())
            reading.shaper = {d: _kbit(values.get(d, "")) for d in DIRECTIONS}
        elif head == "code":
            direction, _, status = rest.partition(" ")
            codes.setdefault(direction, []).append(status)
        elif head.endswith(("-start", "-end")):
            try:
                stamps[head] = {k: float(v or 0) for k, v in (p.split("=", 1) for p in rest.split())}
            except ValueError:
                reading.unreadable = f"the edge printed an unreadable counter line: {line}"
                return reading
    for direction, counter, drops in (("down", "rx", "drops_down"), ("up", "tx", "drops_up")):
        start, end = stamps.get(f"{direction}-start"), stamps.get(f"{direction}-end")
        if not start or not end or end["t"] <= start["t"]:
            reading.unreadable = f"no {direction} window: the edge printed no counters around it"
            return reading
        statuses = codes[direction]
        reading.windows[direction] = Window(
            kbit=(end[counter] - start[counter]) * 8 / (end["t"] - start["t"]) / 1000,
            drops=int(end[drops] - start[drops]),
            # 000 is a stream's last request, cut by the window's end, with no status.
            answered=sum(1 for c in statuses if c.startswith("2")),
            refused=[c for c in statuses if not c.startswith(("2", "000"))],
        )
        if not reading.windows[direction].answered:
            refused = ", ".join(sorted(set(reading.windows[direction].refused))) or "nothing"
            reading.unreadable = f"no {direction} request was answered (the server answered {refused})"
            return reading
    return reading


def report(reading: Reading, when: str) -> list[str]:
    """The lines `make edge-measure` prints, the verdict last."""
    if reading.unreadable:
        return [f"verdict: cannot tell ({reading.unreadable})"]
    lines = [f"at: {when}", f"link: {reading.link or 'unknown'}"]
    for direction, window in reading.windows.items():
        shaped = reading.shaper.get(direction, 0)
        lines.append(
            f"{direction}: {window.kbit:.0f} kbit/s on the adapter, shaper {shaped:.0f} kbit/s, "
            f"{window.drops} shaper drops"
        )
    for direction, window in reading.windows.items():
        if window.refused:
            lines.append(
                f"note: {len(window.refused)} {direction} requests refused ({', '.join(sorted(set(window.refused)))}),"
                f" {window.answered} answered: fewer streams carried part of the window"
            )
    if reading.binding:
        lines.append(
            f"verdict: lower bound only, the shaper bound {' and '.join(reading.binding)}: lift "
            "networking.edge.uplink.bandwidth, provision TAGS=gateway, and measure again"
        )
    else:
        suggested = " ".join(f"{d}_kbit={SHAPE_RATIO * w.kbit:.0f}" for d, w in reading.windows.items())
        lines.append(f"verdict: measured; at {SHAPE_RATIO:.0%} of this run: {suggested} (keep the lower of two runs)")
    return lines


def measure_command(networking: dict[str, Any], seconds: int = SECONDS) -> list[str]:
    """The SSH command that runs the measurement on the edge, over its LAN address."""
    _edge(networking)
    interface = networking["edge"]["uplink"]["interface"]
    return [*_ssh(networking), remote_command(interface, f"ifb4{interface}", seconds)]


def run_measure(networking: dict[str, Any], when: str, seconds: int = SECONDS) -> tuple[int, list[str]]:
    """Measure the line: 0 measured, 2 the shaper bound, 3 cannot be read, 255 SSH."""
    budget = 2 * seconds + 60
    try:
        result = subprocess.run(
            measure_command(networking, seconds),
            check=False,
            stdout=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=budget,
        )
    except subprocess.TimeoutExpired:
        return 255, [f"the edge stopped answering: no reading after {budget} s"]
    if result.returncode == 255:
        return 255, []
    reading = read(result.stdout)
    return reading.code, report(reading, when)
