"""E2E: Ollama public endpoint — health + auth boundary (AI-002, spec).

Covers the public `ollama.kubelab.live` surface introduced by AI-001 / ADR-035
Stage 1: a Traefik `api-key` plugin Middleware gates `/api/*` behind an
X-API-Key header. Staging hosts the same backend without the plugin (VPN-only).

The auth-boundary tests are prod-only (staging has no middleware). The
"wrong key" test uses a hardcoded sentinel — independent of any SOPS
rotation — so it acts as an automated test-of-the-test: if the middleware
ever accepts arbitrary keys, this case fails.
"""

from __future__ import annotations

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

pytestmark = pytest.mark.e2e

# Hardcoded sentinel — deliberately NOT from SOPS, so the test is invariant
# under key rotation and proves the middleware validates the *value*, not just
# header presence. If anyone ever wants to "fix" this by reading from SOPS,
# they break the whole point — see AI-002 proposal.md.
_WRONG_KEY_SENTINEL = "definitely-not-the-real-key"


def _ollama(services_by_name: dict[str, ServiceHealthConfig]) -> ServiceHealthConfig:
    svc = services_by_name.get("ollama")
    if not svc:
        pytest.skip("ollama not registered in this env's config")
    return svc


def _tags_url(svc: ServiceHealthConfig) -> str:
    return f"https://{svc.domain}/api/tags"


def test_ollama_health_authenticated(
    services_by_name: dict[str, ServiceHealthConfig],
    http_client: httpx.Client,
    ollama_api_key: str | None,
    env: str,
) -> None:
    """`/api/tags` returns 200 with a non-empty `models` array.

    prod: requires `X-API-Key` header (middleware-gated).
    staging: VPN-only, no middleware — header is ignored if sent.
    """
    svc = _ollama(services_by_name)
    headers = {}
    if env == "prod":
        # Fixture fails hard in prod when key is missing (see conftest.py);
        # by the time we get here, `ollama_api_key` is guaranteed non-None.
        assert ollama_api_key is not None
        headers["X-API-Key"] = ollama_api_key

    r = http_client.get(_tags_url(svc), headers=headers)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"

    body = r.json()
    models = body.get("models")
    assert isinstance(models, list) and len(models) > 0, (
        f"expected non-empty models list, got: {body!r}"
    )


def test_ollama_auth_boundary_rejects_anon(
    services_by_name: dict[str, ServiceHealthConfig],
    http_client: httpx.Client,
    env: str,
) -> None:
    """Without any auth header, prod returns 403 (plugin enforces presence)."""
    if env != "prod":
        pytest.skip("staging is VPN-only — no middleware gates the endpoint")

    svc = _ollama(services_by_name)
    r = http_client.get(_tags_url(svc))
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"

    body_lower = r.text.lower()
    for leak in ("models", "ollama/", "qwen", "llama"):
        assert leak not in body_lower, (
            f"403 body leaks internal data ({leak!r}): {r.text[:300]}"
        )


def test_ollama_rejects_invalid_key(
    services_by_name: dict[str, ServiceHealthConfig],
    http_client: httpx.Client,
    env: str,
) -> None:
    """Automated test-of-the-test: a key the client KNOWS is wrong returns 403.

    Uses a hardcoded sentinel — independent of any SOPS value — so this case
    proves the middleware validates the key value (not just header presence).
    """
    if env != "prod":
        pytest.skip("staging is VPN-only — no middleware to reject")

    svc = _ollama(services_by_name)
    r = http_client.get(_tags_url(svc), headers={"X-API-Key": _WRONG_KEY_SENTINEL})
    assert r.status_code == 403, (
        f"middleware accepted a known-bad key (expected 403, got {r.status_code}): "
        f"{r.text[:200]}"
    )


def test_ollama_bearer_forward_compat(
    services_by_name: dict[str, ServiceHealthConfig],
    http_client: httpx.Client,
    ollama_api_key: str | None,
    env: str,
) -> None:
    """`Authorization: Bearer <key>` returns 200 — plugin Bearer mode enabled.

    Forward-compat guard for ADR-035 Stage 2 (OIDC/JWT migration). If a future
    Middleware drift disables Bearer mode, this test breaks intentionally to
    force the lockstep update (Middleware + ADR-035 anchored decisions).
    """
    if env != "prod":
        pytest.skip("staging is VPN-only — no middleware to honor Bearer")
    assert ollama_api_key is not None  # fixture fails in prod if missing

    svc = _ollama(services_by_name)
    headers = {"Authorization": f"Bearer {ollama_api_key}"}
    r = http_client.get(_tags_url(svc), headers=headers)
    assert r.status_code == 200, (
        f"Bearer mode appears disabled (expected 200, got {r.status_code}): "
        f"{r.text[:200]}"
    )


def test_ollama_no_key_leak_in_403_body(
    services_by_name: dict[str, ServiceHealthConfig],
    http_client: httpx.Client,
    ollama_api_key: str | None,
    env: str,
) -> None:
    """The 403 response from a rejected request never echoes the real API key.

    Paranoia guard: plugin shouldn't ever include the candidate key value in
    its error body, but verify on a known-bad request — sending the wrong
    sentinel and asserting the SOPS-resolved real key is absent from output.
    """
    if env != "prod":
        pytest.skip("staging is VPN-only — no middleware emits 403 bodies")
    assert ollama_api_key is not None  # fixture fails in prod if missing

    svc = _ollama(services_by_name)
    r = http_client.get(_tags_url(svc), headers={"X-API-Key": _WRONG_KEY_SENTINEL})
    assert r.status_code == 403
    assert ollama_api_key not in r.text, (
        "403 body echoes the real SOPS API key — plugin is leaking secrets"
    )
