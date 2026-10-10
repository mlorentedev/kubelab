"""NOTIFY-001 end-to-end smoke test for the notification fabric.

Drives the *real* entry point — `POST https://<n8n-domain>/webhook/notify` — with
the Bearer secret from SOPS and asserts the fabric behaves:

  - `page` envelope (authenticated)  -> HTTP 200  (routed + delivered)
  - `log`  envelope (authenticated)  -> HTTP 200
  - any envelope WITHOUT the header   -> HTTP 403  (n8n Header Auth, criterion #4)
  - an envelope with a WRONG secret   -> HTTP 403  (the value is compared, not just present)

A 200 from `/webhook/notify` means n8n routed the envelope and apprise accepted
the delivery (apprise returns non-2xx -> n8n's HTTP node errors -> webhook 5xx),
so this also guards the apprise `/status` regression that CrashLooped the pod.
The operator still confirms the messages landed in Slack (#alerts for `page`,
#ops-log for `log`, per ADR-044's NOTIFY-002 addendum): there is no channel
read-back.

Why `verify_tls=False` on staging: `n8n.staging.kubelab.live` is VPN-only and
presents an untrusted cert (Traefik default; the staging IngressRoute carries no
public ACME resolver). The hostname is pinned from the config SSOT — we skip cert
verification for the staging smoke only, never the secret.

Design: the n8n domain is resolved BY SERVICE NAME (walking apps.services.<cat>),
so the smoke is independent of which category n8n lives under.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager

# Webhook contract (infra/n8n/workflows/README.md).
WEBHOOK_PATH = "/webhook/notify"
NOTIFY_SECRET_KEY = "apps.services.automation.notify.webhook_secret"
_AUTH_SCHEME = "Bearer"
_N8N_SERVICE = "n8n"
_HTTP_TIMEOUT = 15

# What a probe presents in the Authorization header.
VALID, MISSING, WRONG = "valid", "missing", "wrong"

# A post() injectable for tests: (url, envelope, headers) -> status code.
PostFn = Callable[[str, dict[str, Any], dict[str, str]], int]


@dataclass(frozen=True)
class Probe:
    """One smoke assertion: send `severity` with a `credential`, expect a code."""

    label: str
    severity: str
    credential: str
    expected_status: int


# The MVP fabric proof: happy path for both tiers + the auth gate (criterion #4).
NOTIFY_SMOKE_PROBES: tuple[Probe, ...] = (
    Probe(label="page (authenticated)", severity="page", credential=VALID, expected_status=200),
    Probe(label="log (authenticated)", severity="log", credential=VALID, expected_status=200),
    Probe(label="unauthenticated reject", severity="page", credential=MISSING, expected_status=403),
    Probe(label="wrong secret reject", severity="page", credential=WRONG, expected_status=403),
)


# ── Pure helpers ──────────────────────────────────────────────────────────────


def build_envelope(
    severity: str, *, title: str, body: str, domain: str = "ops", source: str = "notify-smoke"
) -> dict[str, Any]:
    """Build the webhook request body `{domain, severity, title, body, source}`."""
    return {"domain": domain, "severity": severity, "title": title, "body": body, "source": source}


def webhook_url(domain: str) -> str:
    """The full webhook URL for an n8n public domain."""
    return f"https://{domain}{WEBHOOK_PATH}"


def resolve_service_domain(merged_config: dict[str, Any], name: str) -> str:
    """Return the `domain` of the service `name`, found by walking the config tree.

    Looks under `apps.services.<category>.<name>` and `apps.platform.<name>`, so it
    is agnostic to which category the service lives under. Raises ValueError if the
    service is absent or carries no domain.
    """
    apps = merged_config.get("apps", {})
    buckets: list[dict[str, Any]] = [apps.get("platform", {})]
    buckets.extend(v for v in apps.get("services", {}).values() if isinstance(v, dict))
    for bucket in buckets:
        svc = bucket.get(name)
        if isinstance(svc, dict) and svc.get("domain"):
            return str(svc["domain"])
    raise ValueError(f"service '{name}' has no domain in the merged config — cannot build the webhook URL")


# ── Public API ────────────────────────────────────────────────────────────────


def run_notify_smoke(
    env: str,
    project_root: Path | None = None,
    *,
    cm: ConfigurationManager | None = None,
    post: PostFn | None = None,
    verify_tls: bool = False,
) -> bool:
    """Run the notification-fabric smoke against `env`. Returns True iff every probe matched.

    Fails loudly (returns False, no HTTP) on a missing precondition — absent webhook
    secret or unresolvable n8n domain.
    """
    logger.section(f"notify-smoke — {env.upper()}")

    cm = cm or ConfigurationManager(env, project_root)

    secret = cm.get_secret_by_path(NOTIFY_SECRET_KEY)
    if not secret:
        logger.error(f"Missing SOPS value at '{NOTIFY_SECRET_KEY}' — cannot authenticate the webhook")
        return False

    try:
        domain = resolve_service_domain(cm.get_merged_config(), _N8N_SERVICE)
    except ValueError as exc:
        logger.error(str(exc))
        return False

    url = webhook_url(domain)
    post = post or _default_post(verify_tls)
    logger.info(f"Webhook: {url}")

    all_ok = True
    for probe in NOTIFY_SMOKE_PROBES:
        headers = _auth_headers(probe.credential, secret)
        envelope = build_envelope(
            probe.severity,
            title="notify-smoke",
            body=f"NOTIFY-001 smoke ({env}) — {probe.label}",
            source="notify-smoke",
        )
        ok = _run_probe(probe, post, url, envelope, headers)
        all_ok = all_ok and ok

    if all_ok:
        logger.success("notify-smoke passed — confirm the page/log messages landed in Slack #alerts and #ops-log")
    else:
        logger.error("notify-smoke FAILED — see the probe results above")
    return all_ok


# ── Internals ─────────────────────────────────────────────────────────────────


def _auth_headers(credential: str, secret: str) -> dict[str, str]:
    """The Authorization header a probe sends. A wrong secret is random per run, so it is never the real one."""
    if credential == MISSING:
        return {}
    value = secret if credential == VALID else f"notify-smoke-wrong-{secrets.token_hex(16)}"
    return {"Authorization": f"{_AUTH_SCHEME} {value}"}


def _run_probe(probe: Probe, post: PostFn, url: str, envelope: dict[str, Any], headers: dict[str, str]) -> bool:
    """Fire one probe; log and return whether the status matched the expectation."""
    # No square brackets in the message: the logger renders rich markup and would
    # swallow `[label]` / `[ok]` as style tags.
    try:
        status = post(url, envelope, headers)
    except Exception as exc:  # network error, timeout, TLS — a failed probe, not a crash
        logger.error(f"  {probe.label}: request failed: {exc}")
        return False

    ok = status == probe.expected_status
    mark = "ok" if ok else "FAIL"
    logger.info(f"  {probe.label}: HTTP {status} (expected {probe.expected_status}) -> {mark}")
    return ok


def _default_post(verify_tls: bool) -> PostFn:
    """Real HTTP poster (lazy import so tests never need `requests`)."""
    import requests

    def post(url: str, envelope: dict[str, Any], headers: dict[str, str]) -> int:
        resp = requests.post(url, json=envelope, headers=headers, timeout=_HTTP_TIMEOUT, verify=verify_tls)
        return int(resp.status_code)

    return post
