"""Rotate every break-glass account password in one operation (AUTH-004 AC7).

Each password lives in the application's own database (Grafana, Gitea), not in
anything Argo CD applies. `GF_SECURITY_ADMIN_PASSWORD` only seeds Grafana's first
start, and `gitea-bootstrap.sh` sets the admin password only when it creates the
account. So a rotation that writes SOPS and stops, which is correct for what Argo
CD delivers, would leave SOPS and the service disagreeing. That is exactly the
state in which a break-glass path fails when it is needed.

The order is fixed, and every step after the first can be undone:

1. the current SOPS value must open the service, or nothing is touched (drift);
2. the new value is written to SOPS first (write-ahead);
3. the service is changed, authenticating with the old value, over the same
   private path `toolkit auth break-glass` opens;
4. the new value must open the service and the old one must not;
5. any failure after step 2 restores SOPS, and the service too if it changed.

What gets rotated is derived from the break-glass declaration (every
`{identity, secret}` entry), and a test fails if a declared account has no
reconciler below. No password is ever printed or logged.
"""

from __future__ import annotations

import base64
import json
import secrets as stdlib_secrets
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

#: 32 bytes of entropy, URL-safe: long enough that no policy or brute force matters,
#: and free of characters that need quoting in basic auth or JSON.
PASSWORD_BYTES = 32

Request = Callable[[str, str, Any, str], tuple[int, Any]]


class RotationError(RuntimeError):
    """The service refused a password change."""


class PasswordReconciler(Protocol):
    def set_password(self, base_url: str, user: str, old: str, new: str) -> None: ...

    def verify(self, base_url: str, user: str, password: str) -> bool: ...


@dataclass(frozen=True)
class Target:
    service: str
    identity: str
    secret_key: str


@dataclass(frozen=True)
class Outcome:
    service: str
    ok: bool
    detail: str


def targets(decls: Mapping[str, Mapping[str, Any]]) -> list[Target]:
    """Every break-glass account, from the declaration. Other forms have no password."""
    return [
        Target(service=name, identity=str(decl["identity"]), secret_key=str(decl["secret"]))
        for name, decl in sorted(decls.items())
        if "identity" in decl and "secret" in decl
    ]


def generate_password() -> str:
    return stdlib_secrets.token_urlsafe(PASSWORD_BYTES)


def rotate_one(
    service: str,
    user: str,
    *,
    base_url: str,
    reconciler: PasswordReconciler,
    read: Callable[[], str | None],
    write: Callable[[str], bool],
    generate: Callable[[], str] = generate_password,
) -> Outcome:
    """Rotate one account: SOPS first, then the service, then prove it. See the module docstring."""
    old = read()
    if not old:
        return Outcome(service, False, "no current value in SOPS; nothing was changed")
    if not reconciler.verify(base_url, user, old):
        return Outcome(service, False, "drift: the SOPS value does not open the service; nothing was changed")
    new = generate()
    if not write(new):
        return Outcome(service, False, "could not write the new value to SOPS; nothing was changed")

    try:
        reconciler.set_password(base_url, user, old, new)
    except Exception as exc:  # noqa: BLE001 -- any refusal must end in a restore, never a crash
        return Outcome(service, False, f"the service refused the change ({exc}); " + _restore(write, old))

    if reconciler.verify(base_url, user, new) and not reconciler.verify(base_url, user, old):
        return Outcome(service, True, "rotated; the new value opens the service and the old one does not")

    try:
        reconciler.set_password(base_url, user, new, old)
        service_back = "service reverted"
    except Exception:  # noqa: BLE001
        service_back = "service could NOT be reverted"
    return Outcome(service, False, f"the new value did not verify; {service_back}; " + _restore(write, old))


def _restore(write: Callable[[str], bool], old: str) -> str:
    if write(old):
        return "SOPS restored to the previous value"
    return (
        "SOPS NOT restored: it now holds a value the service may reject. Recover through the "
        "cluster credential (reset the password in the service, then set it in SOPS)"
    )


# --------------------------------------------------------------------------- reconcilers


def _http(method: str, url: str, body: Any, auth: str) -> tuple[int, Any]:
    """Basic-auth JSON request. The credential travels only in the Authorization header."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        return exc.code, {}


class _LoginVerifier:
    """Shared: an account is verified when the password logs in AS THAT USER, not merely on a 200."""

    whoami_path = ""

    def __init__(self, request: Request = _http) -> None:
        self._request = request

    def verify(self, base_url: str, user: str, password: str) -> bool:
        status, body = self._request("GET", base_url + self.whoami_path, None, f"{user}:{password}")
        return status == 200 and isinstance(body, dict) and body.get("login") == user


class GrafanaAdminPassword(_LoginVerifier):
    """Grafana's own change-password endpoint, authenticated with the old password."""

    whoami_path = "/api/user"

    def set_password(self, base_url: str, user: str, old: str, new: str) -> None:
        body = {"oldPassword": old, "newPassword": new, "confirmNew": new}
        status, _ = self._request("PUT", base_url + "/api/user/password", body, f"{user}:{old}")
        if status != 200:
            raise RotationError(f"Grafana answered {status}")


class GiteaAdminPassword(_LoginVerifier):
    """Gitea's admin user edit. `login_name` is `binding:"Required"` in 1.25.5, so it is always sent."""

    whoami_path = "/api/v1/user"

    def set_password(self, base_url: str, user: str, old: str, new: str) -> None:
        body = {"login_name": user, "password": new, "must_change_password": False}
        status, _ = self._request("PATCH", f"{base_url}/api/v1/admin/users/{user}", body, f"{user}:{old}")
        if status != 200:
            raise RotationError(f"Gitea answered {status}")


#: One reconciler per service that declares a break-glass account. A declared
#: account missing here fails `tests/test_break_glass_rotation.py`.
RECONCILERS: dict[str, type[_LoginVerifier]] = {
    "grafana": GrafanaAdminPassword,
    "gitea": GiteaAdminPassword,
}
