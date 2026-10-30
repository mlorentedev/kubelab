"""The edge's 48-hour uplink soak is read from its kernel log (NET-005 B12, #2807).

B12 asks that the uplink adapter survive 48 hours with no reset. The journal holds
about 8 hours on this node (#2702), so the reading comes from rsyslog's `kern.log`,
which the edge keeps for weeks. Two facts about that file, both measured on the
edge on 2026-10-30, shape the reader, and each has a test here:

- A power cut leaves NUL bytes in it, and a plain grep then answers "binary file
  matches" with no lines: a clean-looking soak made of nothing.
- The RPi4 has no clock that survives power-off, so a boot's first lines carry a
  stale time, hours early after a power cut. The file is read in write order and
  the current boot starts at its last kernel banner, never at a timestamp.

The fixtures use the line shapes the edge writes, with documentation-only values.
"""

from __future__ import annotations

import gzip
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]
SHELL = shutil.which("dash") or "/bin/sh"
PASSED, FAILED, IN_PROGRESS, UNREADABLE = 0, 1, 2, 3
HOUR = 3600


def _line(stamp: str, message: str) -> str:
    return f"2026-10-{stamp}+01:00 rpi4 kernel: {message}"


BANNER = "Linux version 6.8.0-1065-raspi (buildd@example) #70-Ubuntu SMP PREEMPT_DYNAMIC"
PROBE = "rtw_8822bu 1-1.4:1.0: Firmware version 27.2.0, H2C version 13"
RENAMED = "rtw_8822bu 1-1.4:1.0 uplink0: renamed from wlan1"
LPS = "rtw_8822bu 1-1.4:1.0: firmware failed to leave lps state"
DISCONNECT = "usb 1-1.4: USB disconnect, device number 3"
FLUSH = "rtw_8822bu 1-1.4:1.0: timed out to flush queue 1"

# A boot that went well, preceded by one whose adapter dropped off USB.
PREVIOUS_BOOT = [
    _line("29T17:19:12.884486", BANNER),
    _line("29T17:19:12.891394", PROBE),
    _line("29T17:32:13.866008", DISCONNECT),
    _line("29T17:32:14.102003", FLUSH),
]
# Stamped before the previous boot's last line: the clock came back stale.
THIS_BOOT = [
    _line("29T17:32:16.307126", BANNER),
    _line("29T22:05:39.472726", PROBE),
    _line("29T22:05:39.951714", RENAMED),
    _line("30T01:21:26.010814", LPS),
]


def _output(log: list[str], uptime: float = 4 * HOUR, state: str = "active", entered_us: int = 14_954_153) -> str:
    rsyslog = [f"ActiveState={state}", f"ActiveEnterTimestampMonotonic={entered_us}"]
    facts = [f"uptime {uptime:.2f}", "NRestarts=0", *rsyslog]
    return "\n".join([*facts, *log]) + "\n"


def _read(*args, **kwargs):
    from toolkit.features.edge_soak import read

    return read(_output(*args, **kwargs))


# ------------------------------------------------------------------ the verdict


def test_a_boot_with_no_reset_is_in_progress_until_48_hours() -> None:
    reading = _read([*PREVIOUS_BOOT, *THIS_BOOT], uptime=4.4 * HOUR)
    assert reading.code == IN_PROGRESS
    assert reading.resets == []


def test_a_boot_with_no_reset_passes_at_48_hours() -> None:
    assert _read([*PREVIOUS_BOOT, *THIS_BOOT], uptime=48 * HOUR).code == PASSED


def test_lps_warnings_are_reported_and_not_counted() -> None:
    """The operator chose to observe them through the soak (#2807)."""
    reading = _read([*THIS_BOOT, _line("30T01:34:58.042741", LPS)], uptime=49 * HOUR)
    assert reading.code == PASSED
    assert len(reading.lps) == 2


def test_the_adapter_dropping_off_usb_fails_the_soak() -> None:
    reading = _read([*THIS_BOOT, _line("30T02:00:00.000000", DISCONNECT)], uptime=49 * HOUR)
    assert reading.code == FAILED
    assert [line for line in reading.resets if "USB disconnect" in line]


def test_the_driver_probing_again_within_the_boot_fails_the_soak() -> None:
    """A second probe in one boot is the adapter coming back: a replug or a reload."""
    reading = _read([*THIS_BOOT, _line("30T02:00:00.000000", PROBE)], uptime=49 * HOUR)
    assert reading.code == FAILED


def test_a_disconnect_on_a_port_the_driver_never_named_is_not_the_adapter() -> None:
    reading = _read([*THIS_BOOT, _line("30T02:00:00.000000", "usb 1-1.2: USB disconnect, device number 5")])
    assert reading.resets == []
    assert "usb 1-1.2: USB disconnect" in reading.other[-1]


def test_a_previous_boot_is_not_read_whatever_its_lines_are_stamped() -> None:
    """The previous boot's disconnect is stamped after this boot's banner, which a
    reader that sorted by time would put inside this boot."""
    assert _read([*PREVIOUS_BOOT, *THIS_BOOT]).resets == []


# ------------------------------------------------------------- failing closed


def test_no_banner_means_the_soak_cannot_be_read() -> None:
    reading = _read(THIS_BOOT[1:], uptime=49 * HOUR)
    assert reading.code == UNREADABLE
    assert "banner" in reading.unreadable


@pytest.mark.parametrize(("state", "entered_us"), [("inactive", 0), ("active", 3 * HOUR * 1_000_000)])
def test_an_rsyslog_that_did_not_run_from_the_boot_means_the_soak_cannot_be_read(state: str, entered_us: int) -> None:
    """Its kern.log could end at an older boot, whose banner would pass for this one."""
    reading = _read([*PREVIOUS_BOOT, *THIS_BOOT], uptime=49 * HOUR, state=state, entered_us=entered_us)
    assert reading.code == UNREADABLE
    assert "rsyslog" in reading.unreadable


def test_no_uptime_means_the_soak_cannot_be_read() -> None:
    from toolkit.features.edge_soak import read

    assert read("\n".join(THIS_BOOT)).code == UNREADABLE


# ------------------------------------------------------------------ the report


def test_the_report_names_no_adapter_mac() -> None:
    """The output lands in the spec's evidence, and the repository is public (ADR-075 C7)."""
    from toolkit.features.edge_soak import report

    log = [*THIS_BOOT, _line("30T02:00:00.000000", "rtw_8822bu 1-1.4:1.0 uplink0: renamed from wlx02005e100001")]
    text = "\n".join(report(_read(log)))
    assert "02005e100001" not in text
    assert "wlx<mac>" in text


def test_the_report_states_the_verdict_and_the_hours() -> None:
    from toolkit.features.edge_soak import report

    lines = report(_read(THIS_BOOT, uptime=4.4 * HOUR))
    assert any("4.4 h of 48" in line for line in lines)
    assert lines[-1].startswith("verdict: in progress")


# --------------------------------------------------------- reading the files


def _run_log_command(log_dir: Path) -> list[str]:
    from toolkit.features.edge_soak import log_command

    result = subprocess.run(
        [SHELL, "-c", log_command(str(log_dir / "kern.log"))], capture_output=True, text=True, check=False
    )
    return result.stdout.splitlines()


def test_the_files_are_read_oldest_first_through_their_compression(tmp_path: Path) -> None:
    """logrotate keeps kern.log.1 plain and gzips the older ones; a boot can span them."""
    with gzip.open(tmp_path / "kern.log.2.gz", "wt") as old:
        old.write(PREVIOUS_BOOT[0] + "\n")
    (tmp_path / "kern.log.1").write_text(PREVIOUS_BOOT[1] + "\n")
    (tmp_path / "kern.log").write_text("\n".join(THIS_BOOT) + "\n")
    assert _run_log_command(tmp_path) == [*PREVIOUS_BOOT[:2], *THIS_BOOT]


def test_nul_bytes_from_a_power_cut_do_not_hide_the_lines(tmp_path: Path) -> None:
    """Measured on the edge: grep answered "binary file matches" and printed nothing."""
    text = "\n".join(THIS_BOOT) + "\n"
    (tmp_path / "kern.log").write_bytes(b"\0" * 512 + text.encode())
    assert _run_log_command(tmp_path) == THIS_BOOT


def test_only_the_lines_the_reading_uses_are_sent(tmp_path: Path) -> None:
    noise = _line("30T01:00:00.000000", "[UFW BLOCK] IN=eth0 OUT= SRC=192.0.2.1 DST=192.0.2.2")
    driver = _line("29T22:05:39.905110", "usbcore: registered new interface driver rtw_8822bu")
    (tmp_path / "kern.log").write_text("\n".join([THIS_BOOT[0], noise, driver, *THIS_BOOT[1:]]) + "\n")
    assert _run_log_command(tmp_path) == THIS_BOOT


# ----------------------------------------------------------- the operator's side


def test_the_command_reaches_the_edge_over_the_lan() -> None:
    from toolkit.features.edge_soak import soak_command

    (node,) = [n for n in NETWORKING["nodes"].values() if "gateway" in (n.get("ansible_groups") or [])]
    command = soak_command(NETWORKING)
    assert command[0] == "ssh"
    assert f"{NETWORKING['ssh_users']['homelab']}@{node['lan_ip']}" in command
    assert "/var/log/kern.log" in command[-1]


@pytest.mark.parametrize(
    ("uptime", "extra", "code"),
    [(49 * HOUR, [], PASSED), (4 * HOUR, [], IN_PROGRESS), (49 * HOUR, [DISCONNECT], FAILED)],
)
def test_the_target_exits_with_the_verdict(uptime: float, extra: list[str], code: int) -> None:
    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    log = [*THIS_BOOT, *(_line("30T02:00:00.000000", m) for m in extra)]
    with mock.patch("toolkit.features.edge_soak.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout=_output(log, uptime=uptime))
        result = CliRunner().invoke(app, ["edge", "soak"])
    assert result.exit_code == code
    assert "verdict:" in result.output


def test_an_ssh_failure_is_not_a_verdict() -> None:
    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    with mock.patch("toolkit.features.edge_soak.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 255, stdout="")
        result = CliRunner().invoke(app, ["edge", "soak"])
    assert result.exit_code == 255
    assert "verdict:" not in result.output


def test_the_make_target_runs_the_command() -> None:
    makefile = (REPO / "Makefile").read_text()
    assert "edge-soak:" in makefile
    assert "$(TOOLKIT) infra edge soak" in makefile
