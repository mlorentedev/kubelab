"""The edge's uplink line rate is measured on the edge, before the shaper (NET-005 AC8, #2876).

`networking.edge.uplink.bandwidth` is set at 90% of the lower of two measured rates,
and re-measured at every site or plan change. Each test pins one fact from the
measurement that set it (#2875): the counters are the uplink adapter's, which sit
before the ingress IFB; a binding shaper yields a lower bound and never a rate; a
server that refuses every request leaves nothing to read; and a stream cut by the
window's end, or an upload's interim 100, is not a refusal.

The outputs are the shapes the edge printed on 2026-10-31, with round numbers.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from toolkit.features import edge_measure as m

REPO = Path(__file__).resolve().parents[1]
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))[
    "networking"
]
UPLINK = NETWORKING["edge"]["uplink"]["interface"]
MEASURED, BINDING, UNREADABLE = 0, 2, 3


def _output(
    *,
    down_bytes: int = 216_000_000,
    up_bytes: int = 30_000_000,
    down_drops: int = 0,
    up_drops: int = 0,
    shaper: str = "50Mbit",
    down_codes: tuple[str, ...] = ("200", "200", "000"),
    up_codes: tuple[str, ...] = ("200", "000"),
) -> str:
    """Sixty seconds per direction: 216 MB down is 28800 kbit/s, 30 MB up is 4000."""
    lines = [
        "link 5560.0 78.0 MBit/s VHT-MCS 8 VHT-NSS 1 ",
        f"shaper down={shaper} up=20Mbit",
        "down-start rx=1000 tx=1000 drops_down=10 drops_up=5 t=100.0",
        *(f"code down {c}" for c in down_codes),
        f"down-end rx={1000 + down_bytes} tx=2000 drops_down={10 + down_drops} drops_up=5 t=160.0",
        f"up-start rx={1000 + down_bytes} tx=2000 drops_down={10 + down_drops} drops_up=5 t=160.0",
        *(f"code up {c}" for c in up_codes),
        f"up-end rx={2000 + down_bytes} tx={2000 + up_bytes}"
        f" drops_down={10 + down_drops} drops_up={5 + up_drops} t=220.0",
    ]
    return "\n".join(lines)


def test_a_run_with_the_shaper_lifted_reads_the_line_and_suggests_90_percent() -> None:
    reading = m.read(_output())
    assert reading.code == MEASURED
    assert round(reading.windows["down"].kbit) == 28800
    assert round(reading.windows["up"].kbit) == 4000
    verdict = m.report(reading, "2026-10-31T03:20Z")[-1]
    assert "down_kbit=25920" in verdict and "up_kbit=3600" in verdict


def test_a_binding_shaper_reads_as_a_lower_bound_never_a_rate() -> None:
    """Measured 03:44Z: 21959 kbit/s against a 24000 shaper with 1950 drops."""
    reading = m.read(_output(down_bytes=165_000_000, down_drops=1950, shaper="24Mbit"))
    assert reading.binding == ["down"]
    assert reading.code == BINDING
    verdict = m.report(reading, "now")[-1]
    assert "lower bound" in verdict and "down_kbit=" not in verdict


def test_drops_below_the_shaped_rate_do_not_bind() -> None:
    """A burst can drop while the line, not the shaper, is the bound."""
    assert m.read(_output(down_bytes=90_000_000, down_drops=40, shaper="24Mbit")).binding == []


def test_a_direction_with_no_answered_request_cannot_be_read() -> None:
    reading = m.read(_output(down_codes=("429", "429", "000")))
    assert reading.code == UNREADABLE
    assert "429" in m.report(reading, "now")[0]


def test_some_refused_requests_are_reported_not_hidden() -> None:
    reading = m.read(_output(down_codes=("200", "429", "429")))
    assert reading.code == MEASURED
    assert any(line.startswith("note: 2 down requests refused (429)") for line in m.report(reading, "now"))


@pytest.mark.parametrize("status", ["000", "100"])
def test_a_cut_stream_or_an_interim_status_is_not_a_refusal(status: str) -> None:
    reading = m.read(_output(up_codes=("200", status)))
    assert reading.windows["up"].refused == ([] if status == "000" else ["100"])
    assert reading.code == MEASURED


def test_missing_counters_cannot_be_read() -> None:
    reading = m.read("link x\nshaper down=24Mbit up=3600Kbit\n")
    assert reading.code == UNREADABLE


@pytest.mark.parametrize(("rate", "kbit"), [("24Mbit", 24000), ("3600Kbit", 3600), ("1Gbit", 1_000_000), ("", 0)])
def test_tc_rates_read_as_kbit(rate: str, kbit: float) -> None:
    assert m._kbit(rate) == kbit


def test_the_command_counts_on_the_ssot_interface_and_its_ifb() -> None:
    command = m.measure_command(NETWORKING)
    script = command[-1]
    assert f"/sys/class/net/{UPLINK}/statistics/rx_bytes" in script
    assert f"dev ifb4{UPLINK}" in script
    lan_ip = NETWORKING["nodes"]["rpi4"]["lan_ip"]
    assert command[-2].endswith(f"@{lan_ip}")
    assert lan_ip not in script


def test_the_remote_script_parses_as_posix_shell() -> None:
    shell = shutil.which("dash") or "/bin/sh"
    script = m.remote_command(UPLINK, f"ifb4{UPLINK}")
    result = subprocess.run([shell, "-n"], input=script, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_the_runbook_cites_the_target() -> None:
    assert "make edge-measure" in (REPO / "docs" / "runbooks" / "lab-edge.md").read_text(encoding="utf-8")
