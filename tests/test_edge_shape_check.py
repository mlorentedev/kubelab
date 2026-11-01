"""B9 times a lab Wi-Fi client's connects under bulk load, with and without the shaper (NET-005 AC8).

Each test pins one rule of `make edge-shape-check`: the shaper is always restored
and read back, even when a window breaks; a restore that cannot be read back fails
the run; a load the server refused, or a probe that recorded nothing, is no
reading; the shaped windows run first; and a bound, when given, judges only them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import edge_shape_check as s

REPO = Path(__file__).resolve().parents[1]
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))[
    "networking"
]


class Hosts:
    """Scripted SSH answers by host and by what the script does."""

    def __init__(
        self,
        *,
        cake: bool = True,
        failing_starts: tuple[int, ...] = (),
        refuse_load: bool = False,
        probe: str = "0.020 200\n",
    ) -> None:
        self.cake = cake
        # Start 0 is the read before the run; 1 and 2 are the restore and its retry.
        self.failing_starts = failing_starts
        self.starts = 0
        self.load_hosts: list[str] = []
        self.refuse_load = refuse_load
        self.probe = probe
        self.log: list[str] = []
        self.rx = 0.0

    def run(self, command: list[str], script: str) -> tuple[int, str]:
        host = command[-1].split("@", 1)[1]
        if s.SHAPER_UNIT in script:
            action = "stop" if "systemctl stop" in script else "start"
            self.log.append(f"shaper {action}")
            if action == "stop":
                self.cake = False
            else:
                self.cake = self.cake if self.starts in self.failing_starts else True
                self.starts += 1
            return 0, f"unit {'active' if self.cake else 'inactive'}\ncake {'yes' if self.cake else 'no'}\n"
        if "statistics" in script:
            self.rx += 30e6
            return 0, f"rx={self.rx:.0f} tx={self.rx / 10:.0f} t={self.rx / 1e6:.1f}\n"
        if "nohup" in script:
            self.log.append(f"probe {host}")
            return 0, "started\n"
        if "cat " in script:
            return 0, self.probe
        if "seq" in script:
            self.load_hosts.append(host)
            self.log.append(f"load {'down' if '__down' in script else 'up'} cake={self.cake}")
            return 0, "code 429\n" if self.refuse_load else "code 200\ncode 200\n"
        raise AssertionError(script)


def _go(hosts: Hosts, bound: float | None = None) -> tuple[int, list[str]]:
    return s.run_shape_check(NETWORKING, bound, run=hosts.run, sleep=lambda _: None)


def test_the_shaped_loads_run_before_the_shaper_comes_off_and_it_is_restored() -> None:
    hosts = Hosts()
    code, lines = _go(hosts)
    assert code == 0
    loads = [entry for entry in hosts.log if entry.startswith("load")]
    assert loads == ["load down cake=True", "load up cake=True", "load down cake=False", "load up cake=False"]
    assert hosts.log[-1] == "shaper start" and hosts.cake
    assert "shaper: restored, CAKE on the uplink" in lines


def test_the_load_runs_on_bee_over_the_lan_and_the_probe_on_rpi3_over_the_tailnet() -> None:
    hosts = Hosts()
    _go(hosts)
    assert f"probe {NETWORKING['nodes']['rpi3']['tailscale_ip']}" in hosts.log
    assert set(hosts.load_hosts) == {NETWORKING["nodes"]["beelink"]["lan_ip"]}


def test_a_window_that_raises_still_restores_the_shaper() -> None:
    hosts = Hosts()
    original = hosts.run

    def breaks_unshaped(command: list[str], script: str) -> tuple[int, str]:
        if "seq" in script and not hosts.cake:
            raise RuntimeError("ssh died")
        return original(command, script)

    with pytest.raises(RuntimeError):
        s.run_shape_check(NETWORKING, None, run=breaks_unshaped, sleep=lambda _: None)
    assert hosts.cake and hosts.log[-1] == "shaper start"


def test_a_restore_that_reads_back_wrong_twice_fails_the_run() -> None:
    code, lines = _go(Hosts(failing_starts=(1, 2)))
    assert code == 3
    assert lines[-1].startswith("verdict: SHAPER NOT RESTORED")


def test_one_failed_restore_is_retried() -> None:
    code, lines = _go(Hosts(failing_starts=(1,)))
    assert code == 0
    assert "shaper: restored, CAKE on the uplink" in lines


def test_a_refused_load_is_no_reading() -> None:
    code, lines = _go(Hosts(refuse_load=True))
    assert code == 3
    assert "the load got no answered request" in lines[1]


def test_a_probe_with_nothing_recorded_is_no_reading() -> None:
    code, _ = _go(Hosts(probe=""))
    assert code == 3


def test_failed_connects_are_counted_and_fail_a_bound() -> None:
    code, lines = _go(Hosts(probe="0.020 200\n0.000 000\n"), bound=100)
    assert code == 1
    assert "1 failed" in lines[1]


def test_a_bound_judges_the_shaped_windows_by_their_p95() -> None:
    assert _go(Hosts(probe="0.040 200\n"), bound=100)[0] == 0
    assert _go(Hosts(probe="0.400 200\n"), bound=100)[0] == 1


def test_an_unshaped_uplink_before_the_run_is_refused() -> None:
    hosts = Hosts(cake=False, failing_starts=(0,))
    code, lines = _go(hosts)
    assert code == 3
    assert "the uplink is not shaped before the run" in lines[-1]
    assert not hosts.load_hosts


def test_the_rates_come_from_the_uplink_counters() -> None:
    _, lines = _go(Hosts())
    # 30 MB in 30 s each window: 8 Mbit/s down, a tenth of it up.
    assert "uplink 8.0 down / 0.8 up Mbit/s" in lines[1]


def test_the_scripts_parse_as_posix_sh() -> None:
    for script in (
        s.load_script("down"),
        s.load_script("up"),
        s.probe_start_script(),
        s.probe_collect_script(),
        s.counters_script("uplink0"),
        s.shaper_script("stop", "uplink0"),
    ):
        subprocess.run(["sh", "-n", "-c", script], check=True)


def test_the_probe_writes_one_line_per_connect(tmp_path: Path) -> None:
    """Run the probe loop for real against a fake curl: the file holds `<time> <code>` lines."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text('#!/bin/sh\nprintf "0.012 200\\n"\n', encoding="utf-8")
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "sleep").chmod(0o755)
    probe = tmp_path / "probe"
    script = s.probe_start_script(seconds=1).replace(s.PROBE_FILE, str(probe)).replace("nohup ", "").replace(" &", "")
    env: dict[str, Any] = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    subprocess.run(["sh", "-c", script], env=env, check=True, timeout=10)
    window = s.Window("t", None, True)
    s.read_probe(probe.read_text(encoding="utf-8"), window)
    assert window.connects_ms and window.connects_ms[0] == pytest.approx(12)
