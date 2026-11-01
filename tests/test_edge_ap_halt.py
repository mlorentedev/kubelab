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
        "before": "up active",
        "bare-unload": "refused modprobe: FATAL: Module brcmfmac is in use.",
        "holder-unload": "ok brcmfmac_wcc",
        **extra,
    }
    return "\n".join(f"{k} {v}" for k, v in lines.items()) + f"\nresult {result}\n"


def _poll(state: str = "up active", boot: str = "b1", ladder: tuple[str, ...] = ()) -> str:
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


def test_a_half_up_ap_is_not_serving() -> None:
    # The interface up with hostapd still starting is not the ladder's test passing.
    code, _ = _go(Edge((0, _injected()), [(0, _poll("up activating"))]))
    assert code == 1


@pytest.mark.parametrize(
    ("result", "verdict"),
    [
        (h.NOT_SERVING, "verdict: the AP was not serving, so nothing was injected"),
        (h.UNLOAD_FAILED, "verdict: the driver would not unload, nothing was injected"),
        (h.NO_UNIT, f"verdict: {h.LIVENESS_UNIT} is not deployed, nothing was injected"),
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
    assert lines == ["verdict: the edge did not answer, nothing was injected"]


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
    (bin_dir / "sudo").write_text('#!/bin/sh\necho called >> "$0.log"\nexit 1\n', encoding="utf-8")
    for tool in ("systemctl", "sudo"):
        (bin_dir / tool).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    out = subprocess.run(["sh", "-c", h.inject_script()], env=env, capture_output=True, text=True, check=True).stdout
    facts = h.parse(out)
    assert (facts["interface"], facts["driver"]) == ("kubelab-test-absent0", "brcmfmac")
    assert facts["before"] == "absent active"
    assert facts["result"] == h.NOT_SERVING
    assert not (bin_dir / "sudo.log").exists()


def test_the_scripts_parse_as_posix_sh() -> None:
    for script in (h.inject_script(), h.poll_script("wlan0", 1)):
        subprocess.run(["sh", "-n", "-c", script], check=True)
