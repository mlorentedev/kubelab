"""Unit tests for Grafana admin identity reconciliation (AUTH-002, #951).

Never spawns a real kubectl or reaches a real Grafana — the transport
(`kubectl_service_port_forward`) and every HTTP call are mocked. CI runners
carry no kubeconfig, and a real prod mutation has no place in a unit test.
"""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import toolkit.features.grafana_admin_identity as gai
from toolkit.features.grafana_admin_identity import (
    GrafanaIdentityUnavailableError,
    check_admin_identity,
    reconcile_admin_identity,
)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    values_dir = tmp_path / "infra" / "config" / "values"
    values_dir.mkdir(parents=True)
    (values_dir / "common.yaml").write_text(
        yaml.safe_dump({"apps": {"auth": {"identities": {"superadmin": "manu", "operator": "operator"}}}})
    )
    return tmp_path


@contextmanager
def _fake_port_forward(env, service, remote_port):
    yield 44444


def _basic_auth_login(req: urllib.request.Request) -> str:
    header = req.headers.get("Authorization") or req.headers.get("authorization")
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
    return decoded.split(":", 1)[0]


class TestCheckAdminIdentity:
    def test_declared_login_already_works(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr(
            "toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret"
        )

        def fake_urlopen(req, timeout=5):
            assert _basic_auth_login(req) == "manu"
            resp = MagicMock()
            resp.read.return_value = json.dumps({"id": 1, "login": "manu"}).encode()
            resp.__enter__.return_value = resp
            return resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = check_admin_identity("staging", project_root)

        assert result.reconciled is True
        assert result.declared_login == "manu"
        assert result.actual_login == "manu"

    def test_declared_fails_bootstrap_default_reveals_the_real_login(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr(
            "toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret"
        )

        def fake_urlopen(req, timeout=5):
            login = _basic_auth_login(req)
            if login == "manu":
                raise urllib.error.HTTPError(url="", code=401, msg="", hdrs=None, fp=None)
            resp = MagicMock()
            resp.read.return_value = json.dumps({"id": 1, "login": "admin"}).encode()
            resp.__enter__.return_value = resp
            return resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = check_admin_identity("prod", project_root)

        assert result.reconciled is False
        assert result.declared_login == "manu"
        assert result.actual_login == "admin"

    def test_neither_login_authenticates(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr(
            "toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret"
        )

        def fake_urlopen(req, timeout=5):
            raise urllib.error.HTTPError(url="", code=401, msg="", hdrs=None, fp=None)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = check_admin_identity("prod", project_root)

        assert result.reconciled is False
        assert result.actual_login is None

    def test_rejected_credential_is_drift_not_unavailability(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """403 is Grafana answering 'no', same as 401 — the drift path, not the raise path.

        Pins the boundary the test below depends on: without this, narrowing
        the handler to 401 alone would pass its own test and silently turn a
        real rejection into an "unavailable".
        """
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr(
            "toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret"
        )

        def fake_urlopen(req, timeout=5):
            if _basic_auth_login(req) == "manu":
                raise urllib.error.HTTPError(url="", code=403, msg="", hdrs=None, fp=None)
            resp = MagicMock()
            resp.read.return_value = json.dumps({"id": 1, "login": "admin"}).encode()
            resp.__enter__.return_value = resp
            return resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = check_admin_identity("prod", project_root)

        assert result.reconciled is False
        assert result.actual_login == "admin"

    def test_server_error_is_unavailable_never_drift(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 5xx means Grafana could not be asked — reporting drift would be a lie.

        The distinction this module is built on ("asked, and drifted" vs
        "could not be asked") collapses if every HTTP status reads as a
        rejected credential: a 503 would render as `reconciled=False`, so
        `--check-only` reports drift that does not exist and `reconcile`
        resets a password because the server hiccuped.
        """
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr(
            "toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret"
        )

        def fake_urlopen(req, timeout=5):
            raise urllib.error.HTTPError(url="", code=503, msg="Service Unavailable", hdrs=None, fp=None)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with pytest.raises(GrafanaIdentityUnavailableError, match="503"):
                check_admin_identity("prod", project_root)

    def test_rate_limit_is_unavailable_never_drift(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """429 is the same category as 5xx: the credential was never judged."""
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr(
            "toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret"
        )

        def fake_urlopen(req, timeout=5):
            raise urllib.error.HTTPError(url="", code=429, msg="Too Many Requests", hdrs=None, fp=None)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with pytest.raises(GrafanaIdentityUnavailableError, match="429"):
                check_admin_identity("prod", project_root)

    def test_no_declared_password_raises(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr("toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: None)

        with pytest.raises(GrafanaIdentityUnavailableError, match="no admin password"):
            check_admin_identity("prod", project_root)


class TestReconcileAdminIdentity:
    def test_already_reconciled_is_a_no_op(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr(
            "toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret"
        )

        def fake_urlopen(req, timeout=5):
            resp = MagicMock()
            resp.read.return_value = json.dumps({"id": 1, "login": "manu"}).encode()
            resp.__enter__.return_value = resp
            return resp

        ran_subprocess = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: ran_subprocess.append(1))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = reconcile_admin_identity("staging", project_root)

        assert result.reconciled is True
        assert result.changed is False
        assert ran_subprocess == [], "an already-reconciled identity must never touch the pod"

    def test_drifted_resets_password_then_renames_the_login(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr(
            "toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret"
        )

        renamed = {}
        effective_login = {"value": "admin"}  # what the DB row's login is, right now

        def fake_urlopen(req, timeout=5):
            if req.get_method() == "PUT":
                body = json.loads(req.data.decode())
                renamed["body"] = body
                effective_login["value"] = body["login"]
                resp = MagicMock()
                resp.__enter__.return_value = resp
                return resp
            login = _basic_auth_login(req)
            if login != effective_login["value"]:
                raise urllib.error.HTTPError(url="", code=401, msg="", hdrs=None, fp=None)
            resp = MagicMock()
            resp.read.return_value = json.dumps(
                {"id": 1, "login": effective_login["value"], "email": "a@b.c"}
            ).encode()
            resp.__enter__.return_value = resp
            return resp

        reset_calls = []

        def fake_run(argv, input=None, capture_output=None, text=None, timeout=None):
            reset_calls.append((argv, input))
            assert "reset-admin-password" in argv
            assert input == "s3cret"
            return MagicMock(returncode=0, stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = reconcile_admin_identity("prod", project_root)

        assert len(reset_calls) == 1
        assert result.reconciled is True
        assert result.changed is True
        assert result.declared_login == "manu"
        assert renamed["body"]["login"] == "manu"

    def test_reset_admin_password_failure_raises(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
        monkeypatch.setattr(
            "toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret"
        )

        def fake_urlopen(req, timeout=5):
            raise urllib.error.HTTPError(url="", code=401, msg="", hdrs=None, fp=None)

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: MagicMock(returncode=1, stderr="boom: pod not found")
        )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with pytest.raises(GrafanaIdentityUnavailableError, match="reset-admin-password failed"):
                reconcile_admin_identity("prod", project_root)
