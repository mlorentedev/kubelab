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
        yaml.safe_dump(
            {
                "apps": {
                    "auth": {"identities": {"superadmin": "manu", "operator": "operator"}},
                    "services": {"security": {"authelia": {"break_glass": {"grafana": BREAK_GLASS}}}},
                }
            }
        )
    )
    return tmp_path


BREAK_GLASS = {
    "login": "breakglass",
    "email": "breakglass@example.test",
    "secret": "apps.services.observability.grafana.admin_password",
}


def _row(login: str, *, email: str = BREAK_GLASS["email"], id: int = 1, server_admin: bool = True) -> bytes:
    """What Grafana's `/api/user` answers for the authenticated row."""
    return json.dumps({"id": id, "login": login, "email": email, "isGrafanaAdmin": server_admin}).encode()


@contextmanager
def _fake_port_forward(env, service, remote_port):
    yield 44444


def _basic_auth_login(req: urllib.request.Request) -> str:
    header = req.headers.get("Authorization") or req.headers.get("authorization")
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
    return decoded.split(":", 1)[0]


def _answer(row: bytes) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = row
    resp.__enter__.return_value = resp
    return resp


def _rejected(code: int = 401) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="", code=code, msg="", hdrs=None, fp=None)


@pytest.fixture
def grafana(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gai, "kubectl_service_port_forward", _fake_port_forward)
    monkeypatch.setattr("toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: "s3cret")


@pytest.mark.usefixtures("grafana")
class TestCheckAdminIdentity:
    def test_the_declared_account_is_row_one(self, project_root: Path) -> None:
        def fake_urlopen(req, timeout=5):
            assert _basic_auth_login(req) == "breakglass"
            return _answer(_row("breakglass"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = check_admin_identity("staging", project_root)

        assert result.reconciled is True
        assert result.declared_login == "breakglass"
        assert result.actual_login == "breakglass"
        assert result.drift == ""

    @pytest.mark.parametrize(
        ("row", "reason"),
        [
            (_row("breakglass", email="info@example.test"), "email"),
            (_row("breakglass", server_admin=False), "Server Admin"),
            (_row("breakglass", id=7), "row id 7"),
        ],
    )
    def test_the_login_alone_is_not_the_account(self, project_root: Path, row: bytes, reason: str) -> None:
        """#951: while row id 1 carries an Authelia user's email, that user's SSO login adopts it.

        A login that works is not enough. The row must also be id 1 (the one
        `reset-admin-password` writes), a Server Admin (the review's revoke needs it),
        and carry the declared email.
        """
        with patch("urllib.request.urlopen", side_effect=lambda req, timeout=5: _answer(row)):
            result = check_admin_identity("prod", project_root)

        assert result.reconciled is False
        assert reason in result.drift

    @pytest.mark.parametrize("current", ["admin", "manu"])
    def test_an_earlier_login_of_row_one_is_found(self, project_root: Path, current: str) -> None:
        """Row id 1 still carries Grafana's bootstrap login, or the superadmin's from before #951."""

        def fake_urlopen(req, timeout=5):
            if _basic_auth_login(req) != current:
                raise _rejected()
            return _answer(_row(current))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = check_admin_identity("prod", project_root)

        assert result.reconciled is False
        assert result.declared_login == "breakglass"
        assert result.actual_login == current

    def test_no_login_authenticates(self, project_root: Path) -> None:
        def fake_urlopen(req, timeout=5):
            raise _rejected()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = check_admin_identity("prod", project_root)

        assert result.reconciled is False
        assert result.actual_login is None

    def test_rejected_credential_is_drift_not_unavailability(self, project_root: Path) -> None:
        """403 is Grafana answering 'no', same as 401 — the drift path, not the raise path.

        Pins the boundary the test below depends on: without this, narrowing
        the handler to 401 alone would pass its own test and silently turn a
        real rejection into an "unavailable".
        """

        def fake_urlopen(req, timeout=5):
            if _basic_auth_login(req) == "breakglass":
                raise _rejected(403)
            return _answer(_row("admin"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = check_admin_identity("prod", project_root)

        assert result.reconciled is False
        assert result.actual_login == "admin"

    def test_server_error_is_unavailable_never_drift(self, project_root: Path) -> None:
        """A 5xx means Grafana could not be asked — reporting drift would be a lie.

        The distinction this module is built on ("asked, and drifted" vs
        "could not be asked") collapses if every HTTP status reads as a
        rejected credential: a 503 would render as `reconciled=False`, so
        `--check-only` reports drift that does not exist and `reconcile`
        resets a password because the server hiccuped.
        """

        def fake_urlopen(req, timeout=5):
            raise urllib.error.HTTPError(url="", code=503, msg="Service Unavailable", hdrs=None, fp=None)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with pytest.raises(GrafanaIdentityUnavailableError, match="503"):
                check_admin_identity("prod", project_root)

    def test_rate_limit_is_unavailable_never_drift(self, project_root: Path) -> None:
        """429 is the same category as 5xx: the credential was never judged."""

        def fake_urlopen(req, timeout=5):
            raise urllib.error.HTTPError(url="", code=429, msg="Too Many Requests", hdrs=None, fp=None)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with pytest.raises(GrafanaIdentityUnavailableError, match="429"):
                check_admin_identity("prod", project_root)

    def test_no_declared_password_raises(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("toolkit.features.secrets_manager.SecretsManager.show_secret", lambda self, env, key: None)

        with pytest.raises(GrafanaIdentityUnavailableError, match="no admin password"):
            check_admin_identity("prod", project_root)


@pytest.mark.usefixtures("grafana")
class TestReconcileAdminIdentity:
    def test_already_reconciled_is_a_no_op(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ran_subprocess = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: ran_subprocess.append(1))

        with patch("urllib.request.urlopen", side_effect=lambda req, timeout=5: _answer(_row("breakglass"))):
            result = reconcile_admin_identity("staging", project_root)

        assert result.reconciled is True
        assert result.changed is False
        assert ran_subprocess == [], "an already-reconciled identity must never touch the pod"

    def test_the_superadmin_row_becomes_the_break_glass_account(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The #951 migration: row id 1 is `manu`, with manu's email, and must become `breakglass`."""
        row = {"login": "manu", "email": "info@example.test"}
        renamed = {}

        def fake_urlopen(req, timeout=5):
            if req.get_method() == "PUT":
                assert req.full_url.endswith("/api/users/1")
                renamed["body"] = json.loads(req.data.decode())
                row.update(login=renamed["body"]["login"], email=renamed["body"]["email"])
                return _answer(b"{}")
            if _basic_auth_login(req) != row["login"]:
                raise _rejected()
            return _answer(_row(row["login"], email=row["email"]))

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
        assert renamed["body"]["login"] == "breakglass"
        assert renamed["body"]["email"] == BREAK_GLASS["email"], "the email is what keeps SSO from adopting the row"

    def test_a_row_other_than_one_is_never_renamed(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The reset wrote row id 1. Another row answering to a candidate login is not the one to rename."""

        def fake_urlopen(req, timeout=5):
            assert req.get_method() != "PUT", "a row other than id 1 must never be renamed"
            if _basic_auth_login(req) != "manu":
                raise _rejected()
            return _answer(_row("manu", id=4))

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(returncode=0, stderr=""))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with pytest.raises(GrafanaIdentityUnavailableError, match="row id 4"):
                reconcile_admin_identity("prod", project_root)

    def test_reset_admin_password_failure_raises(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(req, timeout=5):
            raise _rejected()

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(returncode=1, stderr="boom: pod not found"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with pytest.raises(GrafanaIdentityUnavailableError, match="reset-admin-password failed"):
                reconcile_admin_identity("prod", project_root)
