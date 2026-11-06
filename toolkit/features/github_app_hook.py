"""The kubelab-console GitHub App's webhook, converged from the declaration (CONSOLE-004).

One hook on the App rather than one per repository: it covers every repository
the App is installed on, so a new installation needs nothing here, and it is set
with the App's own credential instead of a personal token.

What the API can set is the delivery config: URL, content type, TLS check and
secret (`PATCH /app/hook/config`). Which events the App subscribes to, and whether
the hook is active, live in the App's settings page and are the operator's step.

GitHub never returns the secret, so a rotation cannot show as drift: the plan
compares the visible fields only, and `resend_secret` writes it on purpose. The
secret is verified by consequence, a delivery the API accepts, never by reading it.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

GITHUB_API = "https://api.github.com"

#: The receiver route in apps/api (`POST /api/forge/webhooks/:forge`).
RECEIVER_PATH = "/api/forge/webhooks/github"

#: The events the API projects (apps/api `forge.ItemFromEvent`). Subscribing is an
#: App setting the API cannot change, so the plan reports a missing one instead.
REQUIRED_EVENTS = ("issues", "pull_request")

#: What `GET /app/hook/config` answering 404 means, and what to do about it.
NO_HOOK = (
    "the App has no webhook (GET /app/hook/config answered 404): in the App's settings, "
    "tick Webhook > Active, enter the URL this command prints, leave the secret empty and save; "
    "then rerun with APPLY=1, which writes the secret"
)


class HookConfigError(RuntimeError):
    """The hook could not be converged; the message names the fix."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def app_jwt(app_id: int | str, private_key_pem: str, *, now: int | None = None) -> str:
    """An RS256 JWT that authenticates as the App itself.

    Backdated a minute for clock drift; GitHub refuses an expiry more than ten
    minutes after issue, so nine is the margin.
    """
    issued = int(time.time() if now is None else now)
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise HookConfigError("the GitHub App private key is not an RSA key")
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64url(
        json.dumps({"iss": str(app_id), "iat": issued - 60, "exp": issued + 540}, separators=(",", ":")).encode()
    )
    signature = key.sign(f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{claims}.{_b64url(signature)}"


@dataclass(frozen=True)
class HookSpec:
    """The delivery config the App's hook must carry."""

    url: str
    content_type: str = "json"
    # "0" verifies TLS. The receiver's certificate is a public Let's Encrypt one.
    insecure_ssl: str = "0"

    def visible(self) -> dict[str, str]:
        return {"url": self.url, "content_type": self.content_type, "insecure_ssl": self.insecure_ssl}


def declared_hook(merged: Mapping[str, Any]) -> HookSpec:
    """Derived from the API's domain, so the hook follows the route if the domain moves."""
    domain = merged["apps"]["platform"]["api"]["domain"]
    return HookSpec(url=f"https://{domain}{RECEIVER_PATH}")


def hook_changes(live: Mapping[str, Any], spec: HookSpec) -> tuple[tuple[str, Any, str], ...]:
    """(field, live, declared) for each visible field that differs. Never the secret."""
    return tuple((k, live.get(k), v) for k, v in spec.visible().items() if str(live.get(k) or "") != v)


class HookAPI(Protocol):
    def get_config(self) -> dict[str, Any]: ...
    def patch_config(self, body: dict[str, Any]) -> None: ...
    def subscribed_events(self) -> set[str]: ...


@dataclass(frozen=True)
class ConvergeResult:
    changes: tuple[tuple[str, Any, str], ...]
    wrote: bool
    # Events the API needs that the App does not subscribe to: the operator's step.
    missing_events: tuple[str, ...] = ()


def converge(
    hooks: HookAPI, spec: HookSpec, *, secret: str, apply: bool, resend_secret: bool = False
) -> ConvergeResult:
    """Plan, and with `apply` write the whole config and read it back."""
    if not secret:
        raise HookConfigError(
            "no webhook secret: set apps.platform.api.forge_github_webhook_secret in prod SOPS, "
            "the same value the API reads as FORGE_GITHUB_WEBHOOK_SECRET"
        )
    subscribed = hooks.subscribed_events()
    missing = tuple(e for e in REQUIRED_EVENTS if e not in subscribed)
    changes = hook_changes(hooks.get_config(), spec)
    if not apply or not (changes or resend_secret):
        return ConvergeResult(changes=changes, wrote=False, missing_events=missing)
    # The whole config every time: a hook with a URL and no secret would deliver
    # unsigned bodies the receiver refuses.
    hooks.patch_config({**spec.visible(), "secret": secret})
    after = hook_changes(hooks.get_config(), spec)
    if after:
        raise HookConfigError(
            f"the write was sent and GitHub accepted it, but the read back still differs: {after}; "
            "rerunning sends it again, which is safe (the secret is the same value)"
        )
    return ConvergeResult(changes=changes, wrote=True, missing_events=missing)


class GitHubAppHooks:
    """`/app/hook/config`, authenticated as the App."""

    def __init__(self, app_id: int | str, private_key_pem: str, *, timeout: float = 15.0) -> None:
        self._app_id = app_id
        self._key = private_key_pem
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {app_jwt(self._app_id, self._key)}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get_config(self) -> dict[str, Any]:
        import requests

        r = requests.get(f"{GITHUB_API}/app/hook/config", headers=self._headers(), timeout=self._timeout)
        if r.status_code == 404:
            raise HookConfigError(NO_HOOK)
        if r.status_code != 200:
            raise HookConfigError(f"GET /app/hook/config answered {r.status_code}")
        return dict(r.json())

    def subscribed_events(self) -> set[str]:
        import requests

        r = requests.get(f"{GITHUB_API}/app", headers=self._headers(), timeout=self._timeout)
        if r.status_code != 200:
            raise HookConfigError(f"GET /app answered {r.status_code}")
        return set(r.json().get("events") or [])

    def patch_config(self, body: dict[str, Any]) -> None:
        import requests

        r = requests.patch(f"{GITHUB_API}/app/hook/config", headers=self._headers(), json=body, timeout=self._timeout)
        # The body is never logged: it carries the secret.
        if r.status_code != 200:
            raise HookConfigError(f"PATCH /app/hook/config answered {r.status_code}")
