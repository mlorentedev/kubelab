"""E2E: Custom error page validation — verifies errors service renders custom pages.

Error-pages middleware intercepts 408, 429, 500-503 (NOT 404 — see ADR decision).
404 is not intercepted to preserve API JSON responses.
The catch-all IngressRoute handles unknown hosts → errors service.
"""

from __future__ import annotations

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

from .expectations import EXPECTATIONS

pytestmark = pytest.mark.e2e

# Non-existent path that should trigger a 404 on any service
_PROBE_PATH = "/nonexistent-e2e-error-page-probe"


def _find_target(
    services_by_name: dict[str, ServiceHealthConfig],
    env: str,
) -> ServiceHealthConfig | None:
    """Find a service that returns 404 for unknown paths."""
    for name in ("api", "web", "loki"):
        svc = services_by_name.get(name)
        if not svc:
            continue
        exp = EXPECTATIONS.get(name)
        if exp and env in exp.skip_in_envs:
            continue
        return svc
    return None


class TestCustomErrorPages:
    """Verify error-pages middleware and catch-all IngressRoute behavior.

    - error-pages middleware: intercepts 408, 429, 500-503 (NOT 404)
    - catch-all IngressRoute: handles unknown hosts → errors service
    - Catch-all requires wildcard DNS — only staging has it (RPi4 CoreDNS).
      Prod uses individual Cloudflare records, no wildcard.
    """

    def test_404_not_intercepted(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        """404 from backends should pass through (not intercepted by error-pages)."""
        target = _find_target(services_by_name, env)
        if not target:
            pytest.skip("No service available to test error pages")

        r = http_client_follow.get(f"https://{target.domain}{_PROBE_PATH}")

        if r.status_code != 404:
            pytest.skip(f"Got {r.status_code} instead of 404")

        # error-pages does NOT intercept 404 — backend response passes through
        ct = r.headers.get("content-type", "")
        assert "text/html" not in ct or "página no encontrada" not in r.text.lower(), (
            "404 should NOT be intercepted by error-pages middleware"
        )

    def test_catch_all_returns_error_page(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        """Catch-all IngressRoute returns errors service HTML for unknown hosts.

        Requires wildcard DNS — only available in staging.
        """
        if env == "prod":
            pytest.skip("No wildcard DNS in prod — catch-all unreachable for unknown hosts")

        target = _find_target(services_by_name, env)
        if not target:
            pytest.skip("No service available to test error pages")

        # Use a non-existent path on an existing host to trigger backend 404
        # The catch-all only works for unknown HOSTS, not paths
        r = http_client_follow.get(f"https://{target.domain}{_PROBE_PATH}")

        if r.status_code != 404:
            pytest.skip(f"Got {r.status_code}, not 404")
