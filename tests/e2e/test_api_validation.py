"""E2E: API input validation and health structure tests."""

from __future__ import annotations

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

pytestmark = pytest.mark.e2e


class TestAPIValidation:
    """POST endpoints must reject invalid or missing input with 400."""

    def _get_api_url(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        env: str,
    ) -> str:
        svc = services_by_name.get("api")
        if not svc:
            pytest.skip("API not in config")
        return f"https://{svc.domain}"

    @pytest.mark.parametrize(
        "path",
        ["/api/subscribe", "/api/unsubscribe", "/api/lead-magnet"],
    )
    def test_missing_email_returns_400(
        self,
        path: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        base = self._get_api_url(services_by_name, env)
        r = http_client.post(f"{base}{path}", json={})
        assert r.status_code == 400, (
            f"POST {path} with empty body: expected 400, got {r.status_code}"
        )

    @pytest.mark.parametrize(
        "path",
        ["/api/subscribe", "/api/lead-magnet"],
    )
    def test_invalid_email_returns_400(
        self,
        path: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        base = self._get_api_url(services_by_name, env)
        r = http_client.post(f"{base}{path}", json={"email": "not-an-email"})
        assert r.status_code == 400, (
            f"POST {path} with invalid email: expected 400, got {r.status_code}"
        )


class TestAPIHealthStructure:
    """GET /health must return well-structured JSON with expected keys."""

    def test_health_json_keys(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc = services_by_name.get("api")
        if not svc:
            pytest.skip("API not in config")

        r = http_client.get(f"https://{svc.domain}/health")
        assert r.status_code == 200

        data = r.json()
        for key in ("service", "status", "version", "timestamp", "checks"):
            assert key in data, f"/health missing key '{key}'"

    def test_health_check_components(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc = services_by_name.get("api")
        if not svc:
            pytest.skip("API not in config")

        r = http_client.get(f"https://{svc.domain}/health")
        assert r.status_code == 200

        data = r.json()
        checks = data.get("checks", [])
        component_names = {c["component"] for c in checks}
        expected = {"database", "external_services", "email", "cache"}
        assert expected.issubset(component_names), (
            f"Missing health check components: {expected - component_names}"
        )
