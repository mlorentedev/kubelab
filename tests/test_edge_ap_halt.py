"""B10 halts the lab Wi-Fi's radio on purpose and watches the ladder bring it back (NET-005 AC13).

Each test pins one rule of `make edge-ap-halt`: nothing is injected unless the AP
serves first; the unload alone is tried, and its refusal recorded, before the
holders go with it; the interface and driver are the deployed liveness unit's;
the wait survives the ladder's reboot; and only an AP serving again passes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from toolkit.features import edge_ap_halt as h

NET: dict[str, Any] = {}
EXEC_START = (
    "{ path=/usr/local/sbin/kubelab-edge-liveness ; "
    "argv[]=/usr/local/sbin/kubelab-edge-liveness wlan0 brcmfmac uplink0 ; ignore_errors=no }"
)


def _injected(result: str = h.INJECTED, **extra: str) -> str:
    lines = {
        "interface": "wlan0",
        "driver": "brcmfmac",
        "boot": "b1",
        "clock": "1000",
        "before": "up ENABLED",
        "bare-unload": "refused modprobe: FATAL: Module brcmfmac is in use.",
        "holder-unload": "ok brcmfmac_wcc",
        "after": "absent",
        **extra,
    }
    return "\n".join(f"{k} {v}" for k, v in lines.items()) + f"\nresult {result}\n"


def _poll(state: str = "up ENABLED", boot: str = "b1", ladder: tuple[str, ...] = ()) -> str:
    return f"boot {boot}\nstate {state}\n" + "".join(f"ladder {line}\n" for line in ladder)


class Edge:
    """A scripted edge: the inject answer, then one answer per poll."""

    def __init__(self, inject: tuple[int, str], polls: list[tuple[int, str]]) -> None:
        self.answers = [inject, *polls]
        self.scripts: list[str] = []
        self.now = 0.0

    def run(self, _net: dict[str, Any], script: str) -> tuple[int, str]:
        self.scripts.append(script)
        return self.answers.pop(0) if self.answers else (0, _poll("absent inactive"))

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _go(edge: Edge) -> tuple[int, list[str]]:
    return h.run_ap_halt(NET, run=edge.run, clock=lambda: edge.now, sleep=edge.sleep)


def test_an_ap_that_serves_again_after_the_reload_passes() -> None:
    reload = "lab Wi-Fi: wlan0 has not served for 3 checks; reloading brcmfmac and restarting hostapd"
    edge = Edge((0, _injected()), [(0, _poll("absent inactive")), (0, _poll(ladder=(reload,)))])
    code, lines = _go(edge)
    assert code == 0
    assert lines[-1] == "verdict: recovered, the AP served again 40 s after the unload"
    assert f"  {reload}" in lines
    assert "edge rebooted: no" in lines


def test_the_unload_alone_is_recorded_before_the_holders_go_with_it() -> None:
    _, lines = _go(Edge((0, _injected()), [(0, _poll())]))
    assert "unload alone: refused modprobe: FATAL: Module brcmfmac is in use." in lines
    assert "unload with holders: ok brcmfmac_wcc" in lines
    assert "after the unload: absent" in lines


def test_a_reboot_with_polls_that_get_no_answer_still_passes_and_says_so() -> None:
    edge = Edge((0, _injected()), [(255, ""), (255, ""), (0, _poll(boot="b2"))])
    code, lines = _go(edge)
    assert code == 0
    assert "edge rebooted: yes" in lines
    assert "polls with no answer: 2" in lines


def test_an_ap_still_down_at_the_deadline_fails() -> None:
    code, lines = _go(Edge((0, _injected()), []))
    assert code == 1
    assert lines[-1].startswith("verdict: FAILED")


@pytest.mark.parametrize("state", ["up DISABLED", "up unanswered", "absent ENABLED"])
def test_only_the_ladder_s_serving_test_counts(state: str) -> None:
    # The interface up with hostapd not ENABLED is not the ladder's test passing.
    code, _ = _go(Edge((0, _injected()), [(0, _poll(state))]))
    assert code == 1


def test_a_recovery_seen_after_the_deadline_is_not_one() -> None:
    edge = Edge((0, _injected()), [])
    late = h.DEADLINE_S + 5

    def run(_net: dict[str, Any], script: str) -> tuple[int, str]:
        edge.scripts.append(script)
        if len(edge.scripts) == 1:
            return 0, _injected()
        edge.now = late  # the poll's SSH session ran past the deadline
        return 0, _poll()

    code, lines = h.run_ap_halt(NET, run=run, clock=lambda: edge.now, sleep=edge.sleep)
    assert code == 1
    assert lines[-1].startswith("verdict: FAILED")


def test_the_last_wait_stops_at_the_deadline() -> None:
    edge = Edge((0, _injected()), [])
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        edge.sleep(seconds)

    edge.now = 0.0
    h.run_ap_halt(NET, run=edge.run, clock=lambda: edge.now, sleep=sleep)
    assert sum(waits) == h.DEADLINE_S


def test_the_poll_keeps_the_unit_s_failures() -> None:
    assert "-e 'Failed to start'" in h.poll_script("wlan0", 1)


@pytest.mark.parametrize(
    ("result", "verdict"),
    [
        (h.NOT_SERVING, "verdict: the AP was not serving, so nothing was injected"),
        (h.UNLOAD_FAILED, "verdict: the driver would not unload, nothing was injected"),
        (h.NO_UNIT, f"verdict: {h.LIVENESS_UNIT} is not deployed, nothing was injected"),
        (h.NOT_HALTED, "verdict: cannot tell, the interface stayed up after the unload, so no halt was observed"),
    ],
)
def test_nothing_injected_exits_3_and_never_polls(result: str, verdict: str) -> None:
    edge = Edge((0, _injected(result)), [])
    code, lines = _go(edge)
    assert (code, lines[-1]) == (3, verdict)
    assert len(edge.scripts) == 1


def test_no_answer_before_the_fault_exits_255() -> None:
    code, lines = _go(Edge((255, ""), []))
    assert code == 255
    # The session may have died after the unload, so the verdict cannot claim nothing happened.
    assert "whether the driver was unloaded is unknown" in lines[-1]


def test_the_ladder_lines_survive_a_reboot_without_repeats() -> None:
    first, second = "line one", "line two"
    edge = Edge(
        (0, _injected()),
        [(0, _poll("absent inactive", ladder=(first,))), (0, _poll(boot="b2", ladder=(first, second)))],
    )
    _, lines = _go(edge)
    assert [line for line in lines if line.startswith("  ")] == [f"  {first}", f"  {second}"]


def test_the_poll_reads_the_ladder_since_the_edge_s_own_clock() -> None:
    edge = Edge((0, _injected(clock="1234")), [(0, _poll())])
    _go(edge)
    assert "--since @1234" in edge.scripts[1]
    assert "/sys/class/net/wlan0/operstate" in edge.scripts[1]


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_the_inject_script_takes_the_interface_and_driver_from_the_unit(tmp_path: Path) -> None:
    """Run the real script with a fake systemctl. Its interface does not exist here,
    so the script must stop at the serving check, before any unload."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exec_start = EXEC_START.replace("wlan0", "kubelab-test-absent0")
    (bin_dir / "systemctl").write_text(
        f'#!/bin/sh\ncase "$1" in show) echo "{exec_start}" ;; is-active) echo active ;; esac\n', encoding="utf-8"
    )
    (bin_dir / "sudo").write_text('#!/bin/sh\necho "$@" >> "$0.log"\nexit 1\n', encoding="utf-8")
    for tool in ("systemctl", "sudo"):
        (bin_dir / tool).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    out = subprocess.run(["sh", "-c", h.inject_script()], env=env, capture_output=True, text=True, check=True).stdout
    facts = h.parse(out)
    assert (facts["interface"], facts["driver"]) == ("kubelab-test-absent0", "brcmfmac")
    assert facts["before"] == "absent unanswered"
    assert facts["result"] == h.NOT_SERVING
    assert "modprobe" not in (bin_dir / "sudo.log").read_text(encoding="utf-8")


FAKE_SUDO = """#!/bin/sh
echo "$*" >> "$0.log"
shift  # -n
case "$*" in
  *hostapd_cli*) echo "state=ENABLED" ;;
  "modprobe -r brcmfmac") echo "modprobe: FATAL: Module brcmfmac is in use."; exit 1 ;;
  "modprobe -r brcmfmac_wcc brcmfmac") rm "$EDGE_SYS_NET/wlan0/operstate" ;;
  *) exit 1 ;;
esac
"""


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_the_inject_script_tries_the_unload_alone_then_with_its_holders(tmp_path: Path) -> None:
    """Run the real script on a fake sysfs whose driver has a holder: the bare
    unload is refused, the unload with the holder takes the interface away, and
    the script observes it gone."""
    bin_dir, net, module = tmp_path / "bin", tmp_path / "net" / "wlan0", tmp_path / "module" / "brcmfmac" / "holders"
    for directory in (bin_dir, net, module):
        directory.mkdir(parents=True)
    (net / "operstate").write_text("up\n", encoding="utf-8")
    (module / "brcmfmac_wcc").touch()
    (bin_dir / "systemctl").write_text(f'#!/bin/sh\necho "{EXEC_START}"\n', encoding="utf-8")
    (bin_dir / "sudo").write_text(FAKE_SUDO, encoding="utf-8")
    for tool in ("systemctl", "sudo"):
        (bin_dir / tool).chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "EDGE_SYS_NET": str(tmp_path / "net"),
        "EDGE_SYS_MODULE": str(tmp_path / "module"),
    }
    out = subprocess.run(["sh", "-c", h.inject_script()], env=env, capture_output=True, text=True, check=True).stdout
    facts = h.parse(out)
    assert facts["before"] == "up ENABLED"
    assert facts["bare-unload"] == "refused modprobe: FATAL: Module brcmfmac is in use."
    assert facts["holder-unload"] == "ok brcmfmac_wcc"
    assert (facts["after"], facts["result"]) == ("absent", h.INJECTED)
    modprobes = [line for line in (bin_dir / "sudo.log").read_text(encoding="utf-8").splitlines() if "modprobe" in line]
    assert modprobes == ["-n modprobe -r brcmfmac", "-n modprobe -r brcmfmac_wcc brcmfmac"]


def test_the_scripts_parse_as_posix_sh() -> None:
    for script in (h.inject_script(), h.poll_script("wlan0", 1)):
        subprocess.run(["sh", "-n", "-c", script], check=True)
