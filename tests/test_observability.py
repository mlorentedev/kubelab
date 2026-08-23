"""Unit and integration tests for Agentic Observability & SRE triage (ADR-064)."""

import datetime
import json
import urllib.error
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from toolkit.features.observability import (
    GrafanaAlertClient,
    LokiClient,
    SlackSreClient,
    SreTriageEngine,
    _parse_time_offset,
    deduplicate_tracebacks,
)
from toolkit.main import app

runner = CliRunner()


class TestTimeOffsetParser:
    def test_parse_seconds(self):
        assert _parse_time_offset("45s") == datetime.timedelta(seconds=45)

    def test_parse_minutes(self):
        assert _parse_time_offset("15m") == datetime.timedelta(minutes=15)

    def test_parse_hours(self):
        assert _parse_time_offset("2h") == datetime.timedelta(hours=2)

    def test_parse_days(self):
        assert _parse_time_offset("7d") == datetime.timedelta(days=7)

    def test_fallback_on_invalid(self):
        assert _parse_time_offset("invalid") == datetime.timedelta(minutes=15)


class TestDeduplicateTracebacks:
    def test_empty_logs(self):
        assert deduplicate_tracebacks([]) == []

    def test_unique_logs(self):
        lines = ["[2026-08-23 02:00:00] Error 1", "[2026-08-23 02:00:01] Error 2"]
        result = deduplicate_tracebacks(lines)
        assert len(result) == 2
        assert "Error 1" in result[0]
        assert "Error 2" in result[1]

    def test_repeated_identical_logs(self):
        lines = [
            "2026-08-23T02:00:00Z Connection refused at 0x7ffd123",
            "2026-08-23T02:00:01Z Connection refused at 0x7ffd456",
            "2026-08-23T02:00:02Z Connection refused at 0x7ffd789",
        ]
        result = deduplicate_tracebacks(lines)
        assert len(result) == 1
        assert "[Repeated 3x]" in result[0]


class TestLokiClient:
    @patch("urllib.request.urlopen")
    def test_query_range_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "status": "success",
                "data": {
                    "resultType": "streams",
                    "result": [
                        {
                            "stream": {"container": "authelia", "node": "vps"},
                            "values": [["1724395000000000000", "level=error msg='Failed login'"]],
                        }
                    ],
                },
            }
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = LokiClient(base_url="http://mock-loki:3100")
        entries = client.query_range('{container="authelia"}')

        assert len(entries) == 1
        assert entries[0]["container"] == "authelia"
        assert entries[0]["node"] == "vps"
        assert "Failed login" in entries[0]["line"]

    @patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused"))
    def test_query_range_connection_error(self, _mock_urlopen):
        client = LokiClient(base_url="http://unreachable:3100")
        entries = client.query_range('{container="authelia"}')
        assert entries == []

    @patch("urllib.request.urlopen")
    def test_query_service_logs_with_level(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "status": "success",
                "data": {
                    "result": [
                        {
                            "stream": {"container": "api"},
                            "values": [["1724395000000000000", "error: database timeout"]],
                        }
                    ]
                },
            }
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = LokiClient()
        lines = client.query_service_logs(service="api", level="error", since="10m")
        assert len(lines) == 1
        assert "database timeout" in lines[0]


class TestGrafanaAlertClient:
    @patch("urllib.request.urlopen")
    def test_get_alerts_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            [
                {
                    "name": "obs015-slo-fast-burn-rate",
                    "state": "alerting",
                    "labels": {"severity": "critical"},
                    "annotations": {
                        "summary": "Fast burn rate on api",
                        "runbook_url": "https://github.com/mlorentedev/kubelab/blob/master/docs/runbooks/alert.md",
                    },
                }
            ]
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = GrafanaAlertClient()
        alerts = client.get_alerts()

        assert len(alerts) == 1
        assert alerts[0]["name"] == "obs015-slo-fast-burn-rate"
        assert alerts[0]["state"] == "alerting"
        assert alerts[0]["severity"] == "critical"


class TestSlackSreClient:
    def test_post_message_mock_mode(self):
        client = SlackSreClient(token=None)
        resp = client.post_message(channel="alerts", text="Test notification", thread_ts="12345")
        assert resp["ok"] is True
        assert resp.get("mock") is True

    @patch("urllib.request.urlopen")
    def test_post_message_api_mode(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"ok": True, "ts": "1724395100.001"}).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = SlackSreClient(token="xoxb-test-token")
        resp = client.post_message(channel="alerts", text="Alert fired", thread_ts="1724395000.000")
        assert resp["ok"] is True
        assert resp["ts"] == "1724395100.001"


class TestSreTriageEngine:
    @patch("toolkit.features.observability.LokiClient.query_service_logs")
    @patch("toolkit.features.observability.GrafanaAlertClient.get_alerts")
    def test_diagnose_oomkilled(self, mock_alerts, mock_logs):
        mock_logs.return_value = ["[2026-08-23 02:00:00] fatal error: runtime out of memory (137)"]
        mock_alerts.return_value = [
            {
                "name": "obs015-quota-mem-warning",
                "state": "alerting",
                "severity": "warning",
                "summary": "Mem limit exceeded on authelia",
            }
        ]

        engine = SreTriageEngine()
        report = engine.diagnose_service(service="authelia")

        assert report["service"] == "authelia"
        assert report["severity"] == "CRITICAL"
        assert "OOMKilled" in report["root_cause"]
        assert len(report["alerts"]) == 1

    @patch("toolkit.features.observability.LokiClient.query_service_logs")
    @patch("toolkit.features.observability.GrafanaAlertClient.get_alerts")
    def test_diagnose_healthy_service(self, mock_alerts, mock_logs):
        mock_logs.return_value = []
        mock_alerts.return_value = []

        engine = SreTriageEngine()
        report = engine.diagnose_service(service="gitea")

        assert report["service"] == "gitea"
        assert report["severity"] == "INFO"
        assert "No active error signatures" in report["root_cause"]


class TestCliCommands:
    @patch("toolkit.features.observability.LokiClient.query_service_logs")
    def test_cli_obs_logs(self, mock_logs):
        mock_logs.return_value = ["[2026-08-23 02:00:00] [authelia@vps] auth failed"]
        result = runner.invoke(app, ["obs", "logs", "--service", "authelia", "--since", "15m"])
        assert result.exit_code == 0
        assert "Telemetry Logs" in result.output
        assert "auth failed" in result.output

    @patch("toolkit.features.observability.GrafanaAlertClient.get_alerts")
    def test_cli_obs_alerts(self, mock_alerts):
        mock_alerts.return_value = [
            {
                "name": "obs007-acme-failure",
                "state": "alerting",
                "severity": "critical",
                "summary": "ACME renew error",
                "runbook_url": "https://example.com",
            }
        ]
        result = runner.invoke(app, ["obs", "alerts"])
        assert result.exit_code == 0
        assert "[FIRING] obs007-acme-failure" in result.output
        assert "ACME renew error" in result.output

    def test_cli_obs_slack(self):
        result = runner.invoke(app, ["obs", "slack", "--channel", "alerts", "--post", "Test alert triage"])
        assert result.exit_code == 0
        assert "Message posted" in result.output

    @patch("toolkit.features.observability.SreTriageEngine.diagnose_service")
    def test_cli_obs_triage(self, mock_triage):
        mock_triage.return_value = {
            "service": "api",
            "severity": "CRITICAL",
            "root_cause": "Database connection pool saturated",
            "recommended_action": "Restart postgres pooler",
            "runbook_url": "https://example.com",
            "sample_errors": ["Error: pool timeout"],
        }
        result = runner.invoke(app, ["obs", "triage", "--service", "api"])
        assert result.exit_code == 0
        assert "AUTOMATED SRE INCIDENT DIAGNOSIS: API" in result.output
        assert "Database connection pool saturated" in result.output
