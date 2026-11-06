"""`make alerts` names every Uptime Kuma monitor that is DOWN (#3156).

On 2026-11-06 Argo CD answered the errors 404 on every path for two hours and
`make alerts` printed only a Grafana backup notice: it read Grafana alone, and
Uptime Kuma, the external half of the monitoring of record (ADR-028), was not
on the path a session reads. These tests hold the read and its failure modes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner
from uptime_kuma_api import MonitorStatus

from toolkit.features import kuma_status
from toolkit.features.kuma_status import KumaUnavailableError, down_monitors

MONITORS = [
    {"id": 1, "name": "Services · Auth · Argo CD", "active": True},
    {"id": 2, "name": "Services · Data · Grafana Prod", "active": True},
    {"id": 3, "name": "Paused one", "active": False},
    {"id": 4, "name": "Never beat", "active": True},
]


def _beat(status: MonitorStatus, time: str, msg: str = "") -> dict:
    return {"status": status, "time": time, "msg": msg}


HEARTBEATS = {
    # Oldest first in the list, but the verdict must come from the newest by time.
    1: [
        _beat(MonitorStatus.DOWN, "2026-11-06 06:10:00.000", "404 - Not Found"),
        _beat(MonitorStatus.UP, "2026-11-06 04:00:00.000"),
    ],
    2: [_beat(MonitorStatus.DOWN, "2026-11-06 04:00:00.000"), _beat(MonitorStatus.UP, "2026-11-06 06:10:00.000")],
    3: [_beat(MonitorStatus.DOWN, "2026-11-06 06:10:00.000")],
}


def test_only_active_monitors_whose_latest_beat_is_down_are_reported() -> None:
    down = down_monitors(MONITORS, HEARTBEATS)
    assert [d["name"] for d in down] == ["Services · Auth · Argo CD"]
    assert down[0]["msg"] == "404 - Not Found"
    assert down[0]["checked"] == "2026-11-06 06:10:00.000"


def test_a_multi_line_message_is_cut_to_its_first_line() -> None:
    beats = {4: [_beat(MonitorStatus.DOWN, "2026-11-06 07:00:00.000", "PING 10.0.0.1 (10.0.0.1)\n--- statistics ---")]}
    assert down_monitors(MONITORS, beats)[0]["msg"] == "PING 10.0.0.1 (10.0.0.1)"


def test_a_failed_connection_raises_instead_of_answering_nothing_is_down() -> None:
    with patch.object(kuma_status, "_connect", side_effect=OSError("no route to host")):
        with pytest.raises(KumaUnavailableError, match="no route to host"):
            kuma_status.ask_down_monitors()


def test_the_connection_is_closed_after_the_read() -> None:
    api = MagicMock()
    api.get_monitors.return_value = MONITORS
    api.get_heartbeats.return_value = HEARTBEATS
    with patch.object(kuma_status, "_connect", return_value=(api, {})):
        assert [d["name"] for d in kuma_status.ask_down_monitors()] == ["Services · Auth · Argo CD"]
    api.disconnect.assert_called_once()


@pytest.fixture
def quiet_grafana(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GRAFANA_URL", "http://mock-grafana:3000")
    with patch("toolkit.features.observability.GrafanaAlertClient.get_alerts", return_value=[]):
        yield


def _invoke(*args: str):
    from toolkit.cli.observability import app

    return CliRunner().invoke(app, ["alerts", *args])


def test_alerts_lists_a_down_monitor_with_its_reason(quiet_grafana) -> None:
    down = [{"name": "Services · Auth · Argo CD", "msg": "404 - Not Found", "checked": "2026-11-06 06:10:00.000"}]
    with patch("toolkit.cli.observability.ask_down_monitors", return_value=down):
        result = _invoke()
    assert "[DOWN] Services · Auth · Argo CD" in result.stdout
    assert "404 - Not Found" in result.stdout
    assert result.exit_code == 0


def test_alerts_says_so_when_uptime_kuma_cannot_be_asked(quiet_grafana) -> None:
    with patch("toolkit.cli.observability.ask_down_monitors", side_effect=KumaUnavailableError("timed out")):
        result = _invoke()
    assert result.exit_code == 1
    assert "Uptime Kuma" in result.output and "timed out" in result.output


def test_alerts_reports_kuma_answered_with_nothing_down(quiet_grafana) -> None:
    with patch("toolkit.cli.observability.ask_down_monitors", return_value=[]):
        result = _invoke()
    assert result.exit_code == 0
    assert "No Uptime Kuma monitor is DOWN" in result.stdout


def test_kuma_is_still_asked_when_grafana_cannot_be(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second source matters most exactly when the first is blind."""
    from toolkit.features.observability import AlertsUnavailableError

    monkeypatch.setenv("GRAFANA_URL", "http://mock-grafana:3000")
    down = [{"name": "Services · Auth · Argo CD", "msg": "404 - Not Found", "checked": "2026-11-06 06:10:00.000"}]
    with (
        patch(
            "toolkit.features.observability.GrafanaAlertClient.get_alerts",
            side_effect=AlertsUnavailableError("connection refused"),
        ),
        patch("toolkit.cli.observability.ask_down_monitors", return_value=down),
    ):
        result = _invoke()
    assert result.exit_code == 1
    assert "Could not ask Grafana" in result.output
    assert "[DOWN] Services · Auth · Argo CD" in result.output


def test_staging_does_not_ask_uptime_kuma(quiet_grafana) -> None:
    """Kuma is not per-environment: it is prod's external half (ADR-028)."""
    with patch("toolkit.cli.observability.ask_down_monitors") as ask:
        _invoke("--env", "staging")
    ask.assert_not_called()
