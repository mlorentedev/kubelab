"""Grafana admin identity reconciliation (AUTH-002, #951).

Grafana's admin row (id 1) is its break-glass account, declared at
`apps.services.security.authelia.break_glass.grafana`: a local account that no
Authelia user can claim, because Grafana refuses every password change on an
SSO-linked account (option A on #951). `GF_SECURITY_ADMIN_USER` and
`GF_SECURITY_ADMIN_EMAIL` are only honoured when Grafana's database is first
created, so a later change to the declaration never reaches an existing
installation's `user` table. Detected functionally, by logging in as the declared
account and reading who that is, never by inspecting the database directly: the
database is the implementation, the login is the contract.
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

# The only statuses that mean "Grafana judged this credential and said no".
# Everything else — 5xx, 429, a proxy's 502 — means the credential was never
# judged at all, which is unavailability, not drift. Collapsing the two makes
# a server hiccup indistinguishable from a wrong password, and this module's
# whole contract rests on telling them apart.
_CREDENTIAL_REJECTED = frozenset({401, 403})


class GrafanaIdentityUnavailableError(RuntimeError):
    """Grafana could not be asked at all — distinct from 'asked, and drifted'."""


@dataclass(frozen=True)
class IdentityCheckResult:
    reconciled: bool
    declared_login: str
    actual_login: str | None  # None only if no known login of row id 1 authenticates
    # True iff THIS call performed the reset+rename. `check_admin_identity`
    # never sets it — a check that mutates state and calls itself a check is
    # the failure mode this module exists to guard against elsewhere.
    changed: bool = False
    # Why the row is not the declared account; empty when it is.
    drift: str = ""


def _resolve_declared_account(project_root: Path) -> tuple[str, str]:
    """Login and email of Grafana's break-glass account, from its declaration and nowhere else.

    Not from any `apps.services.observability.grafana.admin_user` SOPS key: the
    `grafana-admin` Secret's `admin-user` field is built from this same declaration
    (see `k8s_secrets._resolve_grafana_admin`), and reading anything else here would
    classify a real fleet against a value nothing consumes.
    """
    from toolkit.features import break_glass as bg

    with open(project_root / "infra/config/values/common.yaml") as f:
        common = yaml.safe_load(f) or {}
    decl = bg.declarations(common).get("grafana") or {}
    if "secret" not in decl:
        raise GrafanaIdentityUnavailableError("break_glass.grafana declares no account")
    return bg.account_login(decl, common), str(decl.get("email") or "")


def _previous_logins(project_root: Path, declared_login: str) -> list[str]:
    """Logins row id 1 may still carry: one an earlier declaration gave it, or Grafana's
    bootstrap default. Until #951 that was the superadmin, so it comes first, then the
    other declared identities, then the bootstrap default.

    Every login that does not authenticate is a failed attempt, and Grafana blocks a
    login for 5 minutes after 5 consecutive ones (`brute_force_login_protection_max_attempts`).
    The likeliest candidate goes first so that a run costs the fewest failures."""
    with open(project_root / "infra/config/values/common.yaml") as f:
        common = yaml.safe_load(f) or {}
    identities = (common.get("apps", {}).get("auth", {}) or {}).get("identities", {}) or {}
    candidates = [str(identities.get("superadmin") or ""), *(str(v) for v in identities.values()), _BOOTSTRAP_LOGIN]
    return [c for c in dict.fromkeys(candidates) if c and c != declared_login]


def _account_drift(user: dict[str, Any], login: str, email: str) -> str:
    """How the authenticated row differs from the declared break-glass account."""
    problems = []
    if user.get("id") != _BOOTSTRAP_ADMIN_ID:
        problems.append(f"it is row id {user.get('id')}, not {_BOOTSTRAP_ADMIN_ID}")
    if user.get("login") != login:
        problems.append(f"its login is {user.get('login')!r}")
    if email and str(user.get("email") or "").lower() != email.lower():
        problems.append(f"its email is {user.get('email')!r}, not {email!r}")
    if not user.get("isGrafanaAdmin"):
        problems.append("it is not a Server Admin")
    linked = _linked_providers(user)
    if linked:
        problems.append(
            f"it is linked to {', '.join(linked)}, so Grafana refuses to change its password or rename it (#951)"
        )
    return "; ".join(problems)


#: The one link that leaves an account editable: `errOnExternalUser` does not count
#: the auth proxy as a provider (13.0.2, `pkg/api/login.go`), so its rows stay local.
_EDITABLE_LINK = "Auth Proxy"


def _linked_providers(user: dict[str, Any]) -> list[str]:
    """Providers whose link makes Grafana treat the row as external. `/api/user` names the
    newest link in `authLabels`, which is the one `errOnExternalUser` reads."""
    return [label for label in user.get("authLabels") or [] if label != _EDITABLE_LINK]


def _http_get_user(port: int, login: str, password: str) -> dict[str, Any] | None:
    auth = base64.b64encode(f"{login}:{password}".encode()).decode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/user", headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in _CREDENTIAL_REJECTED:
            return None
        raise GrafanaIdentityUnavailableError(f"could not ask Grafana: HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise GrafanaIdentityUnavailableError(f"could not ask Grafana: {e}") from e


def check_admin_identity(env: str, project_root: Path) -> IdentityCheckResult:
    """True iff the declared break-glass account is Grafana's row id 1, as declared, right now.

    This is the "must fail first" check #951 asks for: run it against a
    drifted instance and it reports `reconciled=False` before anything is
    touched, so the later fix has evidence of what it closed. The email is part
    of the contract, not decoration: while it matches an Authelia user, that
    user's SSO login can adopt the row.
    """
    mgr = SecretsManager(project_root=project_root)
    declared_password = mgr.show_secret(env, "apps.services.observability.grafana.admin_password")
    if not declared_password:
        raise GrafanaIdentityUnavailableError(f"no admin password declared for env={env!r}")
    declared_login, declared_email = _resolve_declared_account(project_root)

    with kubectl_service_port_forward(env, "grafana", 3000) as port:
        user = _http_get_user(port, declared_login, declared_password)
        if user is not None:
            drift = _account_drift(user, declared_login, declared_email)
            return IdentityCheckResult(
                reconciled=not drift, declared_login=declared_login, actual_login=user.get("login"), drift=drift
            )
        for candidate in _previous_logins(project_root, declared_login):
            found = _http_get_user(port, candidate, declared_password)
            if found is not None:
                return IdentityCheckResult(
                    reconciled=False,
                    declared_login=declared_login,
                    actual_login=found.get("login"),
                    drift=f"the declared login does not authenticate; {found.get('login')!r} does",
                )
        return IdentityCheckResult(
            reconciled=False,
            declared_login=declared_login,
            actual_login=None,
            drift="no known login of row id 1 authenticates with the declared password",
        )


def reconcile_admin_identity(env: str, project_root: Path) -> IdentityCheckResult:
    """Make Grafana's row id 1 the declared break-glass account: its login and its email.

    Credential-independent by construction: resets the password via
    `grafana cli admin reset-admin-password` first (writes the DB directly
    inside the pod, needs no existing HTTP credential), then renames the
    login and sets the email through the now-authenticated Admin API.
    Idempotent — a call against an already-reconciled instance returns
    immediately.
    """
    result = check_admin_identity(env, project_root)
    if result.reconciled:
        return result

    mgr = SecretsManager(project_root=project_root)
    declared_password = mgr.show_secret(env, "apps.services.observability.grafana.admin_password")
    if not declared_password:
        raise GrafanaIdentityUnavailableError(f"no admin password declared for env={env!r}")
    declared_login, declared_email = _resolve_declared_account(project_root)

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
        user = None
        # The check already found which login row id 1 answers to; try it first, so the
        # reconcile adds no failed attempt towards Grafana's login lockout.
        known = [result.actual_login] if result.actual_login else []
        for candidate in dict.fromkeys([*known, declared_login, *_previous_logins(project_root, declared_login)]):
            user = _http_get_user(port, candidate, declared_password)
            if user is not None:
                break
        if user is None:
            raise GrafanaIdentityUnavailableError(
                "password reset did not authenticate under the declared login or any earlier one"
            )
        # The reset wrote row id 1; anything else answering is not the row to rename.
        if user.get("id") != _BOOTSTRAP_ADMIN_ID:
            raise GrafanaIdentityUnavailableError(
                f"{user.get('login')!r} is row id {user.get('id')}, not {_BOOTSTRAP_ADMIN_ID}; refusing to rename it"
            )
        if not user.get("isGrafanaAdmin"):
            raise GrafanaIdentityUnavailableError(
                "row id 1 is not a Server Admin; no API call can restore that without another Server Admin"
            )
        linked = _linked_providers(user)
        if linked:
            raise GrafanaIdentityUnavailableError(
                f"row id 1 is linked to {', '.join(linked)}: Grafana refuses to rename it or change its password, "
                "and no API call removes the link (#951)"
            )

        if user["login"] != declared_login or str(user.get("email") or "").lower() != declared_email.lower():
            auth = base64.b64encode(f"{user['login']}:{declared_password}".encode()).decode()
            body = json.dumps(
                {
                    "login": declared_login,
                    "email": declared_email or user.get("email", ""),
                    "name": user.get("name", ""),
                }
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
                    f"renaming row id 1 to {declared_login!r} failed: HTTP {e.code}"
                ) from e
            except urllib.error.URLError as e:
                raise GrafanaIdentityUnavailableError(f"renaming row id 1 could not reach Grafana: {e}") from e

        final = _http_get_user(port, declared_login, declared_password)
        drift = (
            "the declared login still cannot log in. If CHECK=1 ran several times just before, Grafana may be "
            "blocking that login for 5 minutes after 5 failed attempts; wait, then re-run with CHECK=1"
            if final is None
            else _account_drift(final, declared_login, declared_email)
        )
        if drift:
            raise GrafanaIdentityUnavailableError(f"the rename did not stick: {drift}")
        return IdentityCheckResult(
            reconciled=True, declared_login=declared_login, actual_login=declared_login, changed=True
        )
