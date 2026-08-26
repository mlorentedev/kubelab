"""Grafana admin identity reconciliation (AUTH-002, #951).

`GF_SECURITY_ADMIN_USER` is only honoured when Grafana's database is first
created — a later change to the declared identity
(`apps.auth.identities.superadmin`) never reaches an existing installation's
`user` table. Detected functionally, by trying to log in as the declared
identity, never by inspecting the database directly: the database is the
implementation, the login is the contract.
"""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from toolkit.features.k8s_kubeconfig import output_path as _kubeconfig_path
from toolkit.features.observability import kubectl_service_port_forward
from toolkit.features.secrets_manager import SecretsManager

# Grafana's own bootstrap default when no admin user has ever been declared —
# the login every fresh instance starts with before any override takes effect.
_BOOTSTRAP_LOGIN = "admin"

# Grafana always creates exactly one user at first boot, always id 1, always
# admin. `grafana cli admin reset-admin-password` defaults to the same
# assumption — this module follows Grafana's own tooling rather than
# inventing a second convention.
_BOOTSTRAP_ADMIN_ID = 1


class GrafanaIdentityUnavailableError(RuntimeError):
    """Grafana could not be asked at all — distinct from 'asked, and drifted'."""


@dataclass(frozen=True)
class IdentityCheckResult:
    reconciled: bool
    declared_login: str
    actual_login: str | None  # None only if even the bootstrap fallback failed to authenticate
    # True iff THIS call performed the reset+rename. `check_admin_identity`
    # never sets it — a check that mutates state and calls itself a check is
    # the failure mode this module exists to guard against elsewhere.
    changed: bool = False


def _resolve_declared_login(project_root: Path) -> str:
    """The declared superadmin, from `apps.auth.identities` and nowhere else.

    Not from any `apps.services.observability.grafana.admin_user` SOPS key —
    that key is not what the `grafana-admin` Secret's `admin-user` field is
    built from (see `k8s_secrets._resolve_superadmin`), and reading it here
    would silently classify a real fleet against a value nothing consumes.
    """
    with open(project_root / "infra/config/values/common.yaml") as f:
        common = yaml.safe_load(f)
    superadmin = common.get("apps", {}).get("auth", {}).get("identities", {}).get("superadmin")
    if not superadmin:
        raise GrafanaIdentityUnavailableError("apps.auth.identities.superadmin is not declared")
    return str(superadmin)


def _http_get_user(port: int, login: str, password: str) -> dict[str, Any] | None:
    auth = base64.b64encode(f"{login}:{password}".encode()).decode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/user", headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError:
        return None
    except urllib.error.URLError as e:
        raise GrafanaIdentityUnavailableError(f"could not ask Grafana: {e}") from e


def check_admin_identity(env: str, project_root: Path) -> IdentityCheckResult:
    """True iff the declared superadmin identity can log in to Grafana right now.

    This is the "must fail first" check #951 asks for: run it against a
    drifted instance and it reports `reconciled=False` before anything is
    touched, so the later fix has evidence of what it closed.
    """
    mgr = SecretsManager(project_root=project_root)
    declared_password = mgr.show_secret(env, "apps.services.observability.grafana.admin_password")
    if not declared_password:
        raise GrafanaIdentityUnavailableError(f"no admin password declared for env={env!r}")
    declared_login = _resolve_declared_login(project_root)

    with kubectl_service_port_forward(env, "grafana", 3000) as port:
        if _http_get_user(port, declared_login, declared_password) is not None:
            return IdentityCheckResult(reconciled=True, declared_login=declared_login, actual_login=declared_login)

        fallback = _http_get_user(port, _BOOTSTRAP_LOGIN, declared_password)
        actual_login = fallback.get("login") if fallback else None
        return IdentityCheckResult(reconciled=False, declared_login=declared_login, actual_login=actual_login)


def reconcile_admin_identity(env: str, project_root: Path) -> IdentityCheckResult:
    """Rename Grafana's admin login to the declared identity.

    Credential-independent by construction: resets the password via
    `grafana cli admin reset-admin-password` first (writes the DB directly
    inside the pod, needs no existing HTTP credential), then renames the
    login through the now-authenticated Admin API. Idempotent — a call
    against an already-reconciled instance returns immediately.
    """
    result = check_admin_identity(env, project_root)
    if result.reconciled:
        return result

    mgr = SecretsManager(project_root=project_root)
    declared_password = mgr.show_secret(env, "apps.services.observability.grafana.admin_password")
    if not declared_password:
        raise GrafanaIdentityUnavailableError(f"no admin password declared for env={env!r}")
    declared_login = result.declared_login

    kubeconfig = _kubeconfig_path(env)
    reset = subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "-n",
            "kubelab",
            "exec",
            "-i",
            "deploy/grafana",
            "--",
            "grafana",
            "cli",
            "admin",
            "reset-admin-password",
            "--user-id",
            str(_BOOTSTRAP_ADMIN_ID),
            "--password-from-stdin",
        ],
        input=declared_password,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if reset.returncode != 0:
        raise GrafanaIdentityUnavailableError(f"reset-admin-password failed: {reset.stderr.strip()}")

    with kubectl_service_port_forward(env, "grafana", 3000) as port:
        user = _http_get_user(port, declared_login, declared_password) or _http_get_user(
            port, _BOOTSTRAP_LOGIN, declared_password
        )
        if user is None:
            raise GrafanaIdentityUnavailableError(
                "password reset did not authenticate under either the declared or bootstrap login"
            )

        if user["login"] != declared_login:
            auth = base64.b64encode(f"{user['login']}:{declared_password}".encode()).decode()
            body = json.dumps(
                {"login": declared_login, "email": user.get("email", ""), "name": user.get("name", "")}
            ).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/users/{user['id']}",
                data=body,
                method="PUT",
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10):
                    pass
            except urllib.error.HTTPError as e:
                raise GrafanaIdentityUnavailableError(
                    f"renaming login to {declared_login!r} failed: HTTP {e.code}"
                ) from e

        final = _http_get_user(port, declared_login, declared_password)
        if final is None:
            raise GrafanaIdentityUnavailableError("rename did not stick — declared identity still cannot log in")
        return IdentityCheckResult(
            reconciled=True, declared_login=declared_login, actual_login=declared_login, changed=True
        )
