"""E2E: Custom error page validation — verifies errors service renders custom pages."""

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
    """Find a service that returns 404 for unknown paths.

    Prefers api/web (return 404 for unknown paths) over SPAs like
    authelia/grafana (return 200 for everything — can't trigger error-pages).
    """
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
    """Services fronted by Traefik with error-pages middleware must return custom HTML errors.

    On Docker Compose: error-pages@file middleware intercepts backend 404s.
    On K3s: error-pages Middleware CRD does the same.
    """

    def test_404_shows_custom_page(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        """Requesting a non-existent path should return custom 404 with Spanish content."""
        target = _find_target(services_by_name, env)
        if not target:
            pytest.skip("No service available to test error pages")

        r = http_client_follow.get(f"https://{target.domain}{_PROBE_PATH}")

        if r.status_code != 404:
            pytest.skip(
                f"Got {r.status_code} instead of 404 — "
                "service may handle unknown paths differently"
            )

        ct = r.headers.get("content-type", "")
        assert "text/html" in ct, (
            f"Expected HTML error page from errors service, got content-type: '{ct}'. "
            "Verify error-pages middleware is applied to the IngressRoute/Traefik route."
        )

        assert "página no encontrada" in r.text.lower(), (
            "404 page should contain Spanish custom error text 'Página no encontrada'"
        )

    def test_404_returns_html(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        """Custom 404 page should be HTML, not the backend's default plaintext."""
        target = _find_target(services_by_name, env)
        if not target:
            pytest.skip("No service available to test error pages")

        r = http_client_follow.get(f"https://{target.domain}{_PROBE_PATH}")

        if r.status_code != 404:
            pytest.skip(f"Got {r.status_code}, not 404")

        ct = r.headers.get("content-type", "")
        assert "text/html" in ct, (
            f"Custom 404 should be HTML, got content-type: '{ct}'. "
            "Verify error-pages middleware is applied."
        )
