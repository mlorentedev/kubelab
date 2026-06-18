"""Tests for notify_smoke — NOTIFY-001 end-to-end smoke of the notification fabric.

Pure helpers (envelope, url, domain resolution) are tested in isolation; the
orchestrator is tested against an injected `post` callable + a stub
ConfigurationManager — no live cluster, no real SOPS, no real HTTP.

Contract under test (resolved against infra/n8n/workflows/README.md + repo SSOT):
  - The webhook entry point is `POST https://<n8n-domain>/webhook/notify`, body
    `{domain, severity, title, body, source}`.
  - Auth is n8n Header Auth: `Authorization: Bearer <webhook_secret>` (RFC 6750).
    A POST WITHOUT the header is rejected (HTTP 403 — criterion #4).
  - A 200 from the webhook means n8n routed the envelope and apprise accepted it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from toolkit.features.notify_smoke import (
    NOTIFY_SECRET_KEY,
    build_envelope,
    resolve_service_domain,
    run_notify_smoke,
    webhook_url,
)

_SECRET = "WEBHOOK_TOKEN"
_DOMAIN = "n8n.staging.kubelab.live"


def _cm(secret: str | None = _SECRET, domain: str | None = _DOMAIN) -> MagicMock:
    """ConfigurationManager stub: webhook secret + merged config carrying n8n."""
    cm = MagicMock()
    cm.get_secret_by_path.side_effect = lambda p: secret if p == NOTIFY_SECRET_KEY else None
    services: dict = {"automation": {}}
    if domain is not None:
        services["automation"]["n8n"] = {"domain": domain, "health_path": "/healthz"}
    cm.get_merged_config.return_value = {"apps": {"services": services}}
    return cm


def _post(behavior) -> MagicMock:
    """post(url, envelope, headers) -> status code, chosen by `behavior(has_auth)`."""
    calls: list[tuple] = []

    def post(url: str, envelope: dict, headers: dict) -> int:
        has_auth = "Authorization" in headers
        calls.append((url, envelope, headers))
        return behavior(has_auth)

    mock = MagicMock(side_effect=post)
    mock.calls = calls
    return mock


# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_build_envelope_carries_all_five_fields() -> None:
    env = build_envelope("page", title="t", body="b", domain="ops", source="notify-smoke")
    assert env == {
        "domain": "ops",
        "severity": "page",
        "title": "t",
        "body": "b",
        "source": "notify-smoke",
    }


def test_webhook_url_is_https_webhook_notify() -> None:
    assert webhook_url("n8n.staging.kubelab.live") == "https://n8n.staging.kubelab.live/webhook/notify"


def test_resolve_service_domain_finds_n8n_regardless_of_category() -> None:
    cfg = {"apps": {"services": {"automation": {"n8n": {"domain": "x.example"}}}}}
    assert resolve_service_domain(cfg, "n8n") == "x.example"


def test_resolve_service_domain_raises_when_absent() -> None:
    cfg = {"apps": {"services": {"core": {"gitea": {"domain": "g.example"}}}}}
    with pytest.raises(ValueError):
        resolve_service_domain(cfg, "n8n")


# ── Orchestrator ──────────────────────────────────────────────────────────────


def test_all_probes_pass_returns_true_and_uses_bearer() -> None:
    post = _post(lambda has_auth: 200 if has_auth else 403)
    assert run_notify_smoke("staging", cm=_cm(), post=post) is True
    # Three probes fired (page, log, unauthenticated reject)
    assert len(post.calls) == 3
    # Authenticated probes carry `Bearer <secret>`, targeting the webhook URL
    auth_calls = [c for c in post.calls if "Authorization" in c[2]]
    assert auth_calls and all(c[2]["Authorization"] == f"Bearer {_SECRET}" for c in auth_calls)
    assert all(c[0] == webhook_url(_DOMAIN) for c in post.calls)


def test_auth_not_rejected_returns_false() -> None:
    # Webhook accepts even an unauthenticated POST (200) -> criterion #4 fails.
    post = _post(lambda has_auth: 200)
    assert run_notify_smoke("staging", cm=_cm(), post=post) is False


def test_delivery_failure_returns_false() -> None:
    # Authenticated POST gets a non-200 (n8n/apprise rejected) -> smoke fails.
    post = _post(lambda has_auth: 500 if has_auth else 403)
    assert run_notify_smoke("staging", cm=_cm(), post=post) is False


def test_missing_secret_fails_without_posting() -> None:
    post = _post(lambda has_auth: 200)
    assert run_notify_smoke("staging", cm=_cm(secret=None), post=post) is False
    assert post.calls == []


def test_missing_n8n_domain_fails_without_posting() -> None:
    post = _post(lambda has_auth: 200)
    assert run_notify_smoke("staging", cm=_cm(domain=None), post=post) is False
    assert post.calls == []
