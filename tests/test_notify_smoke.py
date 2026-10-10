"""Tests for notify_smoke — NOTIFY-001 end-to-end smoke of the notification fabric.

Pure helpers (envelope, url, domain resolution) are tested in isolation; the
orchestrator is tested against an injected `post` callable + a stub
ConfigurationManager — no live cluster, no real SOPS, no real HTTP.

Contract under test (resolved against infra/n8n/workflows/README.md + repo SSOT):
  - The webhook entry point is `POST https://<n8n-domain>/webhook/notify`, body
    `{domain, severity, title, body, source}`.
  - Auth is n8n Header Auth: `Authorization: Bearer <webhook_secret>` (RFC 6750).
    A POST without the header, or with a wrong secret, is rejected (HTTP 403 —
    criterion #4).
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
    """post(url, envelope, headers) -> status code, chosen by `behavior(authorized)`.

    `authorized` is True only for the exact `Bearer <secret>`, as n8n's Header Auth
    compares the value, not the header's presence.
    """
    calls: list[tuple] = []

    def post(url: str, envelope: dict, headers: dict) -> int:
        authorized = headers.get("Authorization") == f"Bearer {_SECRET}"
        calls.append((url, envelope, headers))
        return behavior(authorized)

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
    post = _post(lambda authorized: 200 if authorized else 403)
    assert run_notify_smoke("staging", cm=_cm(), post=post) is True
    # Four probes fired: page, log, no header, wrong secret
    assert len(post.calls) == 4
    sent = [c[2].get("Authorization") for c in post.calls]
    assert sent.count(f"Bearer {_SECRET}") == 2
    assert None in sent
    wrong = [a for a in sent if a not in (None, f"Bearer {_SECRET}")]
    assert len(wrong) == 1 and wrong[0].startswith("Bearer ")
    assert all(c[0] == webhook_url(_DOMAIN) for c in post.calls)


def test_a_webhook_that_only_checks_the_header_is_present_fails() -> None:
    # Accepts any Authorization value: a wrong secret gets 200 -> criterion #4 fails.
    def presence_only(url: str, envelope: dict, headers: dict) -> int:
        return 200 if "Authorization" in headers else 403

    assert run_notify_smoke("staging", cm=_cm(), post=presence_only) is False


def test_the_wrong_secret_is_never_printed_and_never_the_real_one(capsys: pytest.CaptureFixture[str]) -> None:
    post = _post(lambda authorized: 200 if authorized else 403)
    run_notify_smoke("staging", cm=_cm(), post=post)
    wrong = [
        c[2]["Authorization"]
        for c in post.calls
        if c[2].get("Authorization", f"Bearer {_SECRET}") != f"Bearer {_SECRET}"
    ]
    assert wrong and _SECRET not in wrong[0]
    printed = "".join(capsys.readouterr())
    # The log is captured at all (a probe line is in it), so its absence below measures something.
    assert "wrong secret reject: HTTP 403" in printed
    assert wrong[0].removeprefix("Bearer ") not in printed


def test_auth_not_rejected_returns_false() -> None:
    # Webhook accepts even an unauthenticated POST (200) -> criterion #4 fails.
    post = _post(lambda authorized: 200)
    assert run_notify_smoke("staging", cm=_cm(), post=post) is False


def test_delivery_failure_returns_false() -> None:
    # Authenticated POST gets a non-200 (n8n/apprise rejected) -> smoke fails.
    post = _post(lambda authorized: 500 if authorized else 403)
    assert run_notify_smoke("staging", cm=_cm(), post=post) is False


def test_missing_secret_fails_without_posting() -> None:
    post = _post(lambda authorized: 200)
    assert run_notify_smoke("staging", cm=_cm(secret=None), post=post) is False
    assert post.calls == []


def test_missing_n8n_domain_fails_without_posting() -> None:
    post = _post(lambda authorized: 200)
    assert run_notify_smoke("staging", cm=_cm(domain=None), post=post) is False
    assert post.calls == []


# ── CLI ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--env", "prod"], True),
        (["--env", "staging"], False),
        (["--env", "prod", "--no-verify-tls"], False),
        (["--env", "staging", "--verify-tls"], True),
    ],
)
def test_the_cli_verifies_tls_in_prod_unless_told_otherwise(args: list[str], expected: bool) -> None:
    # Staging's webhook presents an untrusted cert (VPN-only); prod's is public ACME,
    # so a default that skipped verification there would accept a broken cert silently.
    from unittest.mock import patch

    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    with (
        patch("toolkit.cli.infra.validate_environment_config"),
        patch("toolkit.features.notify_smoke.run_notify_smoke", return_value=True) as smoke,
    ):
        result = CliRunner().invoke(app, ["n8n", "smoke", *args])

    assert result.exit_code == 0, result.output
    assert smoke.call_args.kwargs["verify_tls"] is expected
