"""E2E: Authentication flow tests — parametrized over auth-protected services."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

from .expectations import EXPECTATIONS, ServiceExpectation

pytestmark = pytest.mark.e2e

# Services that require authentication
_AUTH_SERVICES = sorted(k for k, v in EXPECTATIONS.items() if v.auth_protected)


def _resolve(
    svc_name: str,
    services_by_name: dict[str, ServiceHealthConfig],
    env: str,
) -> tuple[ServiceHealthConfig, ServiceExpectation]:
    exp = EXPECTATIONS[svc_name]
    if env in exp.skip_in_envs:
        pytest.skip(f"{svc_name} skipped in {env}")
    svc = services_by_name.get(svc_name)
    if not svc:
        pytest.skip(f"{svc_name} not in {env} config")
    return svc, exp


class TestAutheliaHealth:
    """Verify Authelia itself is healthy and renders login."""

    def test_health_endpoint(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc = services_by_name.get("authelia")
        if not svc:
            pytest.skip("Authelia not in config")

        r = http_client.get(f"https://{svc.domain}{svc.health_path}")
        assert r.status_code == 200

    def test_login_page_renders(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        svc = services_by_name.get("authelia")
        if not svc:
            pytest.skip("Authelia not in config")

        r = http_client_follow.get(f"https://{svc.domain}/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")


@pytest.mark.parametrize("svc_name", _AUTH_SERVICES)
class TestAuthProtected:
    """Auth-protected services must reject unauthenticated requests."""

    def test_unauthenticated_request_rejected(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc, exp = _resolve(svc_name, services_by_name, env)

        auth_svc = services_by_name.get("authelia")
        auth_domain = auth_svc.domain if auth_svc else None

        r = http_client.get(f"https://{svc.domain}/")

        if r.status_code in (302, 303, 307):
            # Should redirect to auth provider
            location = r.headers.get("location", "")
            if auth_domain:
                parsed = urlparse(location)
                assert auth_domain in parsed.netloc, (
                    f"{svc_name}: redirects to {parsed.netloc}, expected {auth_domain}"
                )
        elif r.status_code == 401:
            pass  # Traefik forwardAuth can return 401 directly
        elif r.status_code == 200 and env == "dev":
            pass  # Dev may not enforce auth via forwardAuth middleware
        else:
            assert r.status_code in exp.unauthenticated_status, (
                f"{svc_name}: expected {exp.unauthenticated_status}, got {r.status_code}"
            )


class TestAuthenticatedAccess:
    """Verify authenticated access to protected services using testuser session."""

    def test_grafana_accessible_with_session(
        self,
        authenticated_client: httpx.Client | None,
        services_by_name: dict[str, ServiceHealthConfig],
        env: str,
    ) -> None:
        if authenticated_client is None:
            pytest.skip("No authenticated session (testuser not provisioned)")

        svc = services_by_name.get("grafana")
        if not svc:
            pytest.skip("Grafana not in config")

        r = authenticated_client.get(f"https://{svc.domain}/api/health")
        assert r.status_code == 200, (
            f"Grafana /api/health with auth session: expected 200, got {r.status_code}"
        )

    def test_traefik_dashboard_accessible_with_session(
        self,
        authenticated_client: httpx.Client | None,
        services_by_name: dict[str, ServiceHealthConfig],
        env: str,
    ) -> None:
        if authenticated_client is None:
            pytest.skip("No authenticated session (testuser not provisioned)")

        exp = EXPECTATIONS.get("traefik")
        if exp and env in exp.skip_in_envs:
            pytest.skip("Traefik dashboard skipped in this env")

        svc = services_by_name.get("traefik")
        if not svc:
            pytest.skip("Traefik not in config")

        r = authenticated_client.get(f"https://{svc.domain}/dashboard/")
        assert r.status_code == 200, (
            f"Traefik /dashboard/ with auth session: expected 200, got {r.status_code}"
        )

    def test_authelia_verify_with_session(
        self,
        authenticated_client: httpx.Client | None,
        services_by_name: dict[str, ServiceHealthConfig],
        env: str,
    ) -> None:
        if authenticated_client is None:
            pytest.skip("No authenticated session (testuser not provisioned)")

        if env == "dev":
            pytest.skip("Authelia /api/verify behaves differently without forwardAuth in dev")

        svc = services_by_name.get("authelia")
        if not svc:
            pytest.skip("Authelia not in config")

        r = authenticated_client.get(f"https://{svc.domain}/api/verify")
        assert r.status_code == 200, (
            f"Authelia /api/verify with auth session: expected 200, got {r.status_code}"
        )
