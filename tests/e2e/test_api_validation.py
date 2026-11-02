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
        assert r.status_code == 400, f"POST {path} with empty body: expected 400, got {r.status_code}"

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
        assert r.status_code == 400, f"POST {path} with invalid email: expected 400, got {r.status_code}"


class TestAPIHealthStructure:
    """The API's probes keep the shapes #2387 gave them (api >= 1.1.6).

    /health is liveness only and touches no dependency, so a Beehiiv outage never
    restarts a healthy pod. /ready names the dependencies it checked.
    """

    def test_health_is_a_liveness_answer(
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
        # Exact keys: a liveness body that grows checks again has started to probe dependencies.
        assert set(data) == {"service", "status", "timestamp"}, f"/health body: {sorted(data)}"
        assert data["status"] == "alive"

    def test_ready_reports_each_dependency(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc = services_by_name.get("api")
        if not svc:
            pytest.skip("API not in config")

        r = http_client.get(f"https://{svc.domain}/ready")
        assert r.status_code == 200, f"/ready answered {r.status_code}: the API's configuration does not load"

        data = r.json()
        # A degraded dependency still answers 200 and keeps the pod in rotation.
        assert data["status"] in {"ready", "degraded"}, data
        components = {c["component"] for c in data.get("checks", [])}
        assert components == {"beehiiv", "email"}, f"/ready components: {sorted(components)}"
