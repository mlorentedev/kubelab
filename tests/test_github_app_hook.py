"""The kubelab-console GitHub App's webhook, converged from the declaration (CONSOLE-004).

No network: the App JWT is checked against the public half of a key made here, and
the hook API is a fake that records what was sent.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from toolkit.features.github_app_hook import (
    GitHubAppHooks,
    HookConfigError,
    HookSpec,
    app_jwt,
    converge,
    declared_hook,
    hook_changes,
)

NOW = 1_800_000_000


def _b64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()


def test_the_app_jwt_is_rs256_signed_and_bounded(key: rsa.RSAPrivateKey) -> None:
    token = app_jwt(5573076, _pem(key), now=NOW)
    header, claims, sig = token.split(".")
    assert json.loads(_b64(header)) == {"alg": "RS256", "typ": "JWT"}
    body = json.loads(_b64(claims))
    # Backdated for clock drift, and GitHub refuses an expiry past ten minutes.
    assert body == {"iss": "5573076", "iat": NOW - 60, "exp": NOW + 540}
    key.public_key().verify(_b64(sig), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())


def test_the_hook_url_is_derived_from_the_api_domain() -> None:
    merged = {"apps": {"platform": {"api": {"domain": "api.kubelab.live"}}}}
    assert declared_hook(merged) == HookSpec(url="https://api.kubelab.live/api/forge/webhooks/github")


def test_the_derived_url_is_the_receiver_route_prod_declares() -> None:
    with open("infra/config/values/prod.yaml", encoding="utf-8") as f:
        prod = yaml.safe_load(f)
    assert declared_hook(prod).url == f"https://{prod['apps']['platform']['api']['domain']}/api/forge/webhooks/github"


def test_changes_name_each_visible_field_that_differs() -> None:
    spec = HookSpec(url="https://api.example/api/forge/webhooks/github")
    live = {"url": "", "content_type": "form", "insecure_ssl": "0", "secret": "********"}
    assert hook_changes(live, spec) == (
        ("url", "", spec.url),
        ("content_type", "form", "json"),
    )
    assert hook_changes({**live, "url": spec.url, "content_type": "json"}, spec) == ()


class FakeHooks:
    def __init__(
        self, live: dict[str, Any], *, ignore_writes: bool = False, events: tuple[str, ...] = ("issues", "pull_request")
    ) -> None:
        self.live = live
        self.events = set(events)
        self.sent: list[dict[str, Any]] = []
        self.ignore_writes = ignore_writes

    def get_config(self) -> dict[str, Any]:
        return dict(self.live)

    def subscribed_events(self) -> set[str]:
        return set(self.events)

    def patch_config(self, body: dict[str, Any]) -> None:
        self.sent.append(body)
        if not self.ignore_writes:
            self.live.update({k: v for k, v in body.items() if k != "secret"})


SPEC = HookSpec(url="https://api.example/api/forge/webhooks/github")
CORRECT = {"url": SPEC.url, "content_type": "json", "insecure_ssl": "0"}


def test_a_correct_hook_is_left_alone() -> None:
    hooks = FakeHooks(dict(CORRECT))
    result = converge(hooks, SPEC, secret="s", apply=True)
    assert result.changes == () and not result.wrote and hooks.sent == []


def test_a_plan_never_writes() -> None:
    hooks = FakeHooks({"url": "", "content_type": "form", "insecure_ssl": "0"})
    result = converge(hooks, SPEC, secret="s", apply=False)
    assert result.changes and not result.wrote and hooks.sent == []


def test_apply_writes_the_whole_config_with_the_secret_and_reads_it_back() -> None:
    hooks = FakeHooks({"url": "", "content_type": "form", "insecure_ssl": "0"})
    result = converge(hooks, SPEC, secret="s3cret", apply=True)
    assert result.wrote
    assert hooks.sent == [{"url": SPEC.url, "content_type": "json", "insecure_ssl": "0", "secret": "s3cret"}]


def test_a_secret_resend_writes_even_when_the_visible_fields_match() -> None:
    # GitHub never returns the secret, so a rotation cannot be detected as drift.
    hooks = FakeHooks(dict(CORRECT))
    result = converge(hooks, SPEC, secret="new", apply=True, resend_secret=True)
    assert result.wrote and hooks.sent[0]["secret"] == "new"


def test_a_write_the_read_back_does_not_show_fails() -> None:
    hooks = FakeHooks({"url": "", "content_type": "json", "insecure_ssl": "0"}, ignore_writes=True)
    with pytest.raises(HookConfigError, match="read back"):
        converge(hooks, SPEC, secret="s", apply=True)


def test_no_secret_refuses_before_any_write() -> None:
    hooks = FakeHooks({"url": "", "content_type": "json", "insecure_ssl": "0"})
    with pytest.raises(HookConfigError, match="secret"):
        converge(hooks, SPEC, secret="", apply=True)
    assert hooks.sent == []


def test_an_unsubscribed_event_is_reported_as_the_operators_step() -> None:
    hooks = FakeHooks(dict(CORRECT), events=("issues",))
    result = converge(hooks, SPEC, secret="s", apply=True)
    assert result.missing_events == ("pull_request",) and not result.wrote


def test_an_app_with_no_webhook_says_how_to_create_one(monkeypatch: pytest.MonkeyPatch, key: rsa.RSAPrivateKey) -> None:
    import requests

    class Answer:
        status_code = 404

    monkeypatch.setattr(requests, "get", lambda *a, **k: Answer())
    with pytest.raises(HookConfigError, match="Webhook > Active"):
        GitHubAppHooks(1, _pem(key)).get_config()
