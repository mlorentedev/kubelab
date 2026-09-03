"""Unit and integration tests for Agentic Observability & SRE triage (ADR-064)."""

import base64
import datetime
import json
import subprocess
import urllib.error

import pytest
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

import toolkit.features.observability as obs
from toolkit.features.observability import (
    AlertsUnavailableError,
    LogsUnavailableError,
    GrafanaAlertClient,
    LokiClient,
    SlackSreClient,
    SreTriageEngine,
    _parse_time_offset,
    deduplicate_tracebacks,
    kubectl_service_port_forward,
    read_cluster_secret_key,
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

    def test_repeated_bracketed_timestamp_logs(self):
        lines = [
            "[2026-08-23 02:00:00] [authelia@vps] user authentication failed",
            "[2026-08-23 02:00:05] [authelia@vps] user authentication failed",
            "[2026-08-23 02:00:10] [authelia@vps] user authentication failed",
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
        """INVERTED 2026-08-24, and the original is why the defect survived.

        This asserted `entries == []` on a connection error — it pinned the
        swallow as the contract, so the CLI's "No logs found in the last 15m"
        was the documented behaviour for an unreachable Loki rather than an
        oversight. A test can hold a bug in place as firmly as it holds a
        feature; this one did, in the sibling of the client that was caught
        answering "All healthy" to a 401.
        """
        client = LokiClient(base_url="http://unreachable:3100")

        with pytest.raises(LogsUnavailableError, match="Connection refused"):
            client.query_range('{container="authelia"}')

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

    @patch("urllib.request.urlopen")
    def test_a_failed_fetch_raises_instead_of_returning_no_alerts(self, mock_urlopen):
        """The defect this replaces, measured on 2026-08-24.

        `get_alerts` swallowed every exception into `[]`, and the CLI renders
        `[]` as "All healthy". So the command answered "All healthy" straight
        after a 401, while two Grafanas were firing an alert that had been up for
        a day and a half. An unreachable Grafana and a quiet one are
        indistinguishable from an empty list, and only one is safe to ignore.
        """
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://grafana.kubelab.live/api/v1/alerts", code=401, msg="Unauthorized", hdrs=None, fp=None
        )

        with pytest.raises(AlertsUnavailableError, match="401"):
            GrafanaAlertClient().get_alerts()

    @patch("urllib.request.urlopen")
    def test_an_empty_answer_is_still_an_answer(self, mock_urlopen):
        """The other half: a Grafana that replies "nothing firing" must NOT be
        turned into an error by the fix above."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"[]"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        assert GrafanaAlertClient().get_alerts() == []


class TestLokiFailsLoudlyToo:
    """The same swallow lived in the sibling client.

    Unlike the alerts one it was never caught lying — Loki answered
    `status: success` with an empty result, so "No logs found" was true. The
    SHAPE was there and the symptom was not, which is the whole reason to fix it
    now rather than after it costs something.
    """

    @patch("urllib.request.urlopen")
    def test_an_unreachable_loki_raises(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        with pytest.raises(LogsUnavailableError, match="Connection refused"):
            LokiClient().query_range(query='{container="authelia"}')

    @patch("urllib.request.urlopen")
    def test_a_successful_empty_window_is_not_an_error(self, mock_urlopen):
        """A quiet service must still read as quiet, or the fix trades one wrong
        answer for another."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status":"success","data":{"result":[]}}'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        assert LokiClient().query_range(query='{container="authelia"}') == []


class TestKubectlServicePortForward:
    """OBS-019 transport: mirrors k8s_connect.ts_bridge_tunnel's own test shape.

    Never spawns a real kubectl — CI runners have no kubeconfig, and a "unit"
    test that happens to succeed locally because a real one exists on the
    developer's machine is exactly the non-hermetic trap this guards against.
    """

    def _mock_proc(self) -> MagicMock:
        proc = MagicMock()
        proc.poll.return_value = None
        return proc

    def test_missing_kubeconfig_raises_before_spawning_anything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(obs, "_kubeconfig_path", lambda env: __import__("pathlib").Path("/nonexistent"))
        with pytest.raises(RuntimeError, match="no kubeconfig"):
            with kubectl_service_port_forward("staging", "grafana", 3000):
                pass

    def test_yields_local_port_and_terminates_on_exit(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_kubeconfig = tmp_path / "kubelab-staging-config"
        fake_kubeconfig.write_text("")
        monkeypatch.setattr(obs, "_kubeconfig_path", lambda env: fake_kubeconfig)
        mock_proc = self._mock_proc()
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: mock_proc)
        monkeypatch.setattr(obs, "_port_listening", lambda *a, **kw: True)
        monkeypatch.setattr(obs, "find_free_port", lambda: 54321)

        with kubectl_service_port_forward("staging", "grafana", 3000) as port:
            assert port == 54321

        mock_proc.terminate.assert_called_once()

    def test_process_exiting_early_raises_before_yielding(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_kubeconfig = tmp_path / "kubelab-staging-config"
        fake_kubeconfig.write_text("")
        monkeypatch.setattr(obs, "_kubeconfig_path", lambda env: fake_kubeconfig)
        mock_proc = self._mock_proc()
        mock_proc.poll.return_value = 1  # exited immediately, e.g. "svc/grafana" not found
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: mock_proc)
        monkeypatch.setattr(obs, "_port_listening", lambda *a, **kw: False)

        with pytest.raises(RuntimeError, match="exited early"):
            with kubectl_service_port_forward("staging", "grafana", 3000):
                pytest.fail("body must not run when the tunnel never came up")

        mock_proc.terminate.assert_called_once()


class TestReadClusterSecretKey:
    def test_missing_kubeconfig_returns_none_without_spawning_kubectl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(obs, "_kubeconfig_path", lambda env: __import__("pathlib").Path("/nonexistent"))
        called = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(1))
        assert read_cluster_secret_key("staging", "grafana-admin", "alerts-ro-token") is None
        assert called == []

    def test_decodes_the_base64_value_on_success(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_kubeconfig = tmp_path / "kubelab-staging-config"
        fake_kubeconfig.write_text("")
        monkeypatch.setattr(obs, "_kubeconfig_path", lambda env: fake_kubeconfig)
        encoded = base64.b64encode(b"glsa_secrettoken").decode()
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: MagicMock(returncode=0, stdout=encoded)
        )
        assert read_cluster_secret_key("staging", "grafana-admin", "alerts-ro-token") == "glsa_secrettoken"

    def test_nonzero_exit_returns_none(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_kubeconfig = tmp_path / "kubelab-staging-config"
        fake_kubeconfig.write_text("")
        monkeypatch.setattr(obs, "_kubeconfig_path", lambda env: fake_kubeconfig)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(returncode=1, stdout=""))
        assert read_cluster_secret_key("staging", "grafana-admin", "alerts-ro-token") is None


class TestGrafanaClientTransportSelection:
    """`_grafana_client` picks the direct-URL escape hatch or the port-forward transport."""

    def test_grafana_url_set_skips_the_transport_entirely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolkit.cli import observability as cli_obs

        monkeypatch.setenv("GRAFANA_URL", "http://mock-grafana:3000")

        def _boom(*a, **kw):
            raise AssertionError("port-forward must not be attempted when GRAFANA_URL is set")

        monkeypatch.setattr(cli_obs, "kubectl_service_port_forward", _boom)

        with cli_obs._grafana_client("prod") as client:
            assert client.base_url == "http://mock-grafana:3000"

    def test_without_grafana_url_wraps_port_forward_and_reads_the_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from contextlib import contextmanager

        from toolkit.cli import observability as cli_obs

        monkeypatch.delenv("GRAFANA_URL", raising=False)

        @contextmanager
        def fake_port_forward(env, service, remote_port):
            assert (env, service, remote_port) == ("staging", "grafana", 3000)
            yield 44444

        monkeypatch.setattr(cli_obs, "kubectl_service_port_forward", fake_port_forward)
        monkeypatch.setattr(cli_obs, "read_cluster_secret_key", lambda *a, **kw: "glsa_token")

        with cli_obs._grafana_client("staging") as client:
            assert client.base_url == "http://127.0.0.1:44444"
            assert client.token == "glsa_token"

    def test_transport_failure_becomes_alerts_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolkit.cli import observability as cli_obs

        monkeypatch.delenv("GRAFANA_URL", raising=False)

        def _raise(*a, **kw):
            raise TimeoutError("port-forward to svc/grafana (env=prod) did not come up in 15s")

        monkeypatch.setattr(cli_obs, "kubectl_service_port_forward", _raise)

        with pytest.raises(AlertsUnavailableError, match="could not reach Grafana"):
            with cli_obs._grafana_client("prod"):
                pytest.fail("body must not run when the transport never came up")


class TestAlertsCommandFailsLoudly:
    """A blind check must not exit 0, in either output mode."""

    @patch("toolkit.features.observability.GrafanaAlertClient.get_alerts")
    def test_the_cli_exits_non_zero_when_grafana_cannot_be_asked(self, mock_get, monkeypatch):
        from typer.testing import CliRunner

        from toolkit.cli.observability import app

        # GRAFANA_URL takes the direct-URL escape hatch in `_grafana_client`,
        # skipping the `kubectl port-forward` transport — this test is about
        # `get_alerts()` failing, not about reaching a real cluster from CI.
        monkeypatch.setenv("GRAFANA_URL", "http://mock-grafana:3000")
        mock_get.side_effect = AlertsUnavailableError("Grafana alert fetch failed: HTTP Error 401: Unauthorized")
        result = CliRunner().invoke(app, ["alerts"])

        assert result.exit_code == 1

    @patch("toolkit.features.observability.GrafanaAlertClient.get_alerts")
    def test_json_mode_emits_an_error_object_never_an_empty_array(self, mock_get, monkeypatch):
        """`[]` is what a machine consumer reads as "no alerts firing"."""
        from typer.testing import CliRunner

        from toolkit.cli.observability import app

        monkeypatch.setenv("GRAFANA_URL", "http://mock-grafana:3000")
        mock_get.side_effect = AlertsUnavailableError("boom")
        result = CliRunner().invoke(app, ["alerts", "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["alerts"] is None
        assert "boom" in payload["error"]


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
    def test_cli_obs_logs(self, mock_logs, monkeypatch):
        # LOKI_URL is the direct-URL escape hatch, set here for the same reason
        # the alerts tests below set GRAFANA_URL: this asserts on OUTPUT, not on
        # transport. Without it `logs` opens a real `kubectl port-forward` — which
        # fails on a runner with no cluster, and on a workstation succeeds by
        # reaching the live prod Loki. Neither is what this test is asking about.
        monkeypatch.setenv("LOKI_URL", "http://mock-loki:3100")
        mock_logs.return_value = ["[2026-08-23 02:00:00] [authelia@vps] auth failed"]
        result = runner.invoke(app, ["obs", "logs", "--service", "authelia", "--since", "15m"])
        assert result.exit_code == 0
        assert "Telemetry Logs" in result.output
        assert "auth failed" in result.output

    @patch("toolkit.features.observability.GrafanaAlertClient.get_alerts")
    def test_cli_obs_alerts(self, mock_alerts, monkeypatch):
        monkeypatch.setenv("GRAFANA_URL", "http://mock-grafana:3000")
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

    @patch("toolkit.features.observability.LokiClient.query_service_logs")
    def test_cli_obs_logs_json(self, mock_logs, monkeypatch):
        monkeypatch.setenv("LOKI_URL", "http://mock-loki:3100")  # see test_cli_obs_logs
        mock_logs.return_value = ["[2026-08-23 02:00:00] [authelia@vps] auth failed"]
        result = runner.invoke(app, ["obs", "logs", "--service", "authelia", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["service"] == "authelia"
        assert len(parsed["lines"]) == 1

    @patch("toolkit.features.observability.GrafanaAlertClient.get_alerts")
    def test_cli_obs_alerts_json(self, mock_alerts, monkeypatch):
        monkeypatch.setenv("GRAFANA_URL", "http://mock-grafana:3000")
        mock_alerts.return_value = [{"name": "obs007-acme-failure", "state": "alerting", "severity": "critical"}]
        result = runner.invoke(app, ["obs", "alerts", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "obs007-acme-failure"

    @patch("toolkit.features.observability.SreTriageEngine.diagnose_service")
    def test_cli_obs_triage_json(self, mock_triage, monkeypatch):
        mock_triage.return_value = {
            "service": "api",
            "severity": "CRITICAL",
            "root_cause": "Database connection pool saturated",
            "recommended_action": "Restart postgres pooler",
            "runbook_url": "https://example.com",
            "sample_errors": [],
        }
        # TOOL-055 AC4. `triage` now opens both transports before diagnosing, so
        # without these the test opens a real port-forward: it FAILS on a CI
        # runner with no kubeconfig, and -- worse -- PASSES on a workstation by
        # reaching live prod. Setting both makes the context managers take their
        # documented escape-hatch branch and stay hermetic, matching the sibling
        # commands' tests.
        monkeypatch.setenv("LOKI_URL", "http://mock-loki:3100")
        monkeypatch.setenv("GRAFANA_URL", "http://mock-grafana:3000")

        result = runner.invoke(app, ["obs", "triage", "--service", "api", "--json"])

        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["service"] == "api"
        assert parsed["severity"] == "CRITICAL"


class TestTriageNeverDiagnosesFromASourceItDidNotReach:
    """TOOL-055 (#1534): `obs triage` built both clients from `default_factory`.

    It asked `127.0.0.1:3100` for logs and the default URL for alerts, while its
    siblings `logs` and `alerts` had already been given `--env` and a port-forward
    transport (OBS-019, #1530).

    Why this command is the one that mattered: `obs logs` against the wrong Loki
    prints "No logs found", which is wrong but visibly a non-answer.
    `diagnose_service` turns the same emptiness into `severity: INFO` and "No
    active error signatures detected in telemetry window" -- an assertion of
    HEALTH, sourced from a Loki it never contacted. The indistinguishable
    emptiness is laundered into a diagnosis.

    Measured 2026-09-01: `0.0.0.0:3100` on the workstation was held by an
    unrelated local Loki, so the wrong answer was the machine's default state.
    """

    def test_triage_port_forwards_to_the_named_env_for_both_sources(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import contextlib

        import toolkit.cli.observability as obs_cli

        calls: list[tuple] = []

        @contextlib.contextmanager
        def fake_forward(env, service, port):
            calls.append((env, service, port))
            yield 55555

        monkeypatch.delenv("LOKI_URL", raising=False)
        monkeypatch.delenv("GRAFANA_URL", raising=False)
        monkeypatch.setattr(obs_cli, "kubectl_service_port_forward", fake_forward)
        monkeypatch.setattr(obs_cli, "read_cluster_secret_key", lambda *a, **kw: "tok")
        monkeypatch.setattr(obs_cli.LokiClient, "query_service_logs", lambda self, **kw: [])
        monkeypatch.setattr(obs_cli.GrafanaAlertClient, "get_alerts", lambda self: [])

        result = runner.invoke(app, ["obs", "triage", "--env", "prod", "--service", "api"])

        assert result.exit_code == 0, result.output
        assert calls == [("prod", "loki", 3100), ("prod", "grafana", 3000)], (
            "triage must reach BOTH of the named environment's sources through a "
            f"port-forward rather than a default URL; got {calls!r}"
        )

    def test_an_unreachable_loki_is_an_error_not_a_verdict_of_health(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The defect this ticket exists for, asserted directly.

        Before the fix an unreached Loki produced `severity: INFO` and "no active
        error signatures". A machine consumer reading that JSON concludes the
        service is fine. It must get an error and a NULL severity instead --
        `null` rather than a missing key, because an absent field reads as benign
        to the same consumer.
        """
        import contextlib

        import toolkit.cli.observability as obs_cli

        @contextlib.contextmanager
        def fake_forward(env, service, port):
            raise RuntimeError("no kubeconfig for prod")
            yield  # pragma: no cover

        monkeypatch.delenv("LOKI_URL", raising=False)
        monkeypatch.delenv("GRAFANA_URL", raising=False)
        monkeypatch.setattr(obs_cli, "kubectl_service_port_forward", fake_forward)

        result = runner.invoke(app, ["obs", "triage", "--env", "prod", "--service", "api", "--json"])

        assert result.exit_code == 1, result.output
        parsed = json.loads(result.output)
        assert parsed["severity"] is None, (
            f"an unreached source must not yield a severity; got {parsed.get('severity')!r}. "
            "INFO here is the exact defect: a verdict of health from a source nobody asked."
        )
        assert parsed["report"] is None
        assert "no kubeconfig for prod" in parsed["error"]

    def test_a_grafana_failure_is_not_reported_as_a_loki_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Measured against prod 2026-09-02, on the first real run of the fix.

        `ObservabilityUnavailableError` subclasses `RuntimeError`, and
        `_loki_client` caught `(RuntimeError, TimeoutError)` to wrap transport
        failures. So an `AlertsUnavailableError` raised INSIDE the nested `with`
        body was caught on the way out and relabelled, producing:

            could not reach Loki in prod: could not reach Grafana in prod: 401

        Loki was working perfectly. An operator reads the first clause and goes
        to debug the wrong backend -- the error message is an instrument, and it
        reported the same thing under two different causes.

        Pre-existing in `_loki_client`, and invisible until something nested the
        two context managers. TOOL-055 is the first thing that does.
        """
        import contextlib

        import toolkit.cli.observability as obs_cli

        @contextlib.contextmanager
        def fake_forward(env, service, port):
            yield 55555

        monkeypatch.delenv("LOKI_URL", raising=False)
        monkeypatch.delenv("GRAFANA_URL", raising=False)
        monkeypatch.setattr(obs_cli, "kubectl_service_port_forward", fake_forward)
        monkeypatch.setattr(obs_cli, "read_cluster_secret_key", lambda *a, **kw: "")
        monkeypatch.setattr(obs_cli.LokiClient, "query_service_logs", lambda self, **kw: [])

        def unauthorised(self):
            raise AlertsUnavailableError("Grafana alert fetch failed: HTTP Error 401: Unauthorized")

        monkeypatch.setattr(obs_cli.GrafanaAlertClient, "get_alerts", unauthorised)

        result = runner.invoke(app, ["obs", "triage", "--env", "prod", "--service", "api", "--json"])

        assert result.exit_code == 1
        error = json.loads(result.output)["error"]
        assert "Grafana" in error, f"the failing backend must be named; got {error!r}"
        assert "Loki" not in error, (
            f"Loki answered, and must not be blamed for Grafana's failure; got {error!r}. "
            "Re-wrapping an already-precise error re-attributes it, and the operator "
            "debugs the wrong backend."
        )

    def test_the_human_output_says_it_is_not_a_clean_bill_of_health(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-JSON operator must not read the failure as 'nothing wrong'."""
        import contextlib

        import toolkit.cli.observability as obs_cli

        @contextlib.contextmanager
        def fake_forward(env, service, port):
            raise RuntimeError("connection refused")
            yield  # pragma: no cover

        monkeypatch.delenv("LOKI_URL", raising=False)
        monkeypatch.delenv("GRAFANA_URL", raising=False)
        monkeypatch.setattr(obs_cli, "kubectl_service_port_forward", fake_forward)

        result = runner.invoke(app, ["obs", "triage", "--env", "prod", "--service", "api"])

        assert result.exit_code == 1
        assert "NOT a clean bill of health" in result.output, (
            f"the failure must say what it is not; got: {result.output!r}"
        )


class TestLogsAsksTheEnvironmentYouNamed:
    """OBS-019: `obs logs` had no `--env` while its sibling `obs alerts` did.

    `LokiClient()` defaults to `127.0.0.1:3100`, so the command asked whatever
    was listening there. Measured 2026-09-01: it printed "No logs found" for
    `--service crowdsec --since 15m` while prod's Loki held 20 matching lines
    in that window -- a dev Loki was bound to that port on the workstation.

    This is a THIRD failure mode, distinct from the two the module already
    separates. An unreachable Loki raises; a quiet one returns []. A *wrong*
    one answers `status: success` with an empty result, so it is
    indistinguishable from the quiet case and reports someone else's silence as
    the answer. The guard is that the command must route through the named
    environment rather than a default port.
    """

    def test_logs_port_forwards_to_the_named_env_rather_than_localhost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import contextlib

        import toolkit.cli.observability as obs_cli

        calls: list[tuple] = []

        @contextlib.contextmanager
        def fake_forward(env, service, port):
            calls.append((env, service, port))
            yield 55555

        monkeypatch.delenv("LOKI_URL", raising=False)
        monkeypatch.setattr(obs_cli, "kubectl_service_port_forward", fake_forward)
        monkeypatch.setattr(
            obs_cli.LokiClient, "query_service_logs", lambda self, **kw: []
        )

        result = runner.invoke(app, ["obs", "logs", "--env", "prod", "--service", "crowdsec"])

        assert result.exit_code == 0, result.output
        assert calls == [("prod", "loki", 3100)], (
            "logs must reach the named environment's Loki through a port-forward, "
            "not whatever is bound to the default 127.0.0.1:3100"
        )

    def test_an_empty_window_names_the_loki_it_asked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """'No logs found' without a source reads as authoritative. It is not."""
        import contextlib

        import toolkit.cli.observability as obs_cli

        @contextlib.contextmanager
        def fake_forward(env, service, port):
            yield 55555

        monkeypatch.delenv("LOKI_URL", raising=False)
        monkeypatch.setattr(obs_cli, "kubectl_service_port_forward", fake_forward)
        monkeypatch.setattr(
            obs_cli.LokiClient, "query_service_logs", lambda self, **kw: []
        )

        result = runner.invoke(app, ["obs", "logs", "--env", "prod", "--service", "crowdsec"])

        assert "No logs found" in result.output
        assert "127.0.0.1:55555" in result.output, (
            f"the empty-window message must name the Loki it asked; got: {result.output!r}"
        )
