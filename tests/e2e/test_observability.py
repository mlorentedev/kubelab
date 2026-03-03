"""E2E: Observability stack tests — Grafana API and Loki readiness."""

from __future__ import annotations

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

pytestmark = pytest.mark.e2e


class TestGrafanaAPI:
    """Grafana must be healthy and have Loki configured as a datasource."""

    def test_grafana_health(
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
        assert r.status_code == 200

        data = r.json()
        assert "database" in data, "Grafana /api/health missing 'database' key"

    def test_grafana_has_loki_datasource(
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

        r = authenticated_client.get(f"https://{svc.domain}/api/datasources")

        if r.status_code in (401, 403):
            pytest.skip("Grafana datasources API requires admin — testuser may lack access")

        assert r.status_code == 200, (
            f"Grafana /api/datasources: expected 200, got {r.status_code}"
        )

        datasources = r.json()
        loki_sources = [ds for ds in datasources if ds.get("type") == "loki"]
        assert loki_sources, "Grafana has no Loki datasource configured"


class TestLokiReadiness:
    """Loki must be ready and accepting queries."""

    def test_loki_ready(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc = services_by_name.get("loki")
        if not svc:
            pytest.skip("Loki not in config")

        r = http_client.get(f"https://{svc.domain}/ready")
        # Loki may be behind auth (302) depending on environment config
        assert r.status_code in (200, 302), (
            f"Loki /ready: expected 200 or 302 (auth redirect), got {r.status_code}"
        )

    def test_loki_query_recent_logs(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        if env == "dev":
            pytest.skip("Loki query test only on staging/prod (namespace-based)")

        svc = services_by_name.get("loki")
        if not svc:
            pytest.skip("Loki not in config")

        r = http_client.get(
            f"https://{svc.domain}/loki/api/v1/query",
            params={"query": '{namespace="kubelab"}', "limit": "1"},
        )
        # Accept 200 (results found) or auth-redirects
        assert r.status_code in (200, 302, 401), (
            f"Loki query: expected 200/302/401, got {r.status_code}"
        )
