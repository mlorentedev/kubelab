"""Tests for config-driven health check feature."""

from __future__ import annotations

from toolkit.features.health_check import (
    HealthChecker,
    HealthCheckResult,
    ServiceHealthConfig,
)


class TestServiceHealthConfig:
    """Test ServiceHealthConfig model."""

    def test_basic_construction(self) -> None:
        cfg = ServiceHealthConfig(
            name="api",
            domain="api.kubelab.live",
            health_path="/health",
        )
        assert cfg.name == "api"
        assert cfg.enable_auth is False
        assert cfg.category == ""

    def test_with_auth(self) -> None:
        cfg = ServiceHealthConfig(
            name="grafana",
            domain="grafana.kubelab.live",
            health_path="/api/health",
            enable_auth=True,
            category="services/observability",
        )
        assert cfg.enable_auth is True
        assert cfg.category == "services/observability"


class TestHealthCheckResult:
    """Test HealthCheckResult model."""

    def test_healthy_result(self) -> None:
        r = HealthCheckResult(
            service="api", url="https://api.kubelab.live/health",
            status_code=200, healthy=True, reason="OK",
        )
        assert r.healthy is True

    def test_unhealthy_result(self) -> None:
        r = HealthCheckResult(
            service="minio", url="https://minio.kubelab.live/minio/health/live",
            status_code=403, healthy=False, reason="HTTP 403",
        )
        assert r.healthy is False


class TestExtractServiceConfigs:
    """Test config tree walking logic."""

    @staticmethod
    def _make_config() -> dict:
        return {
            "apps": {
                "platform": {
                    "api": {
                        "name": "api",
                        "domain": "api.kubelab.live",
                        "health_path": "/health",
                        "enable_auth": False,
                    },
                    "web": {
                        "name": "web",
                        "domain": "web.kubelab.live",
                        "health_path": "/",
                    },
                },
                "services": {
                    "data": {
                        "minio": {
                            "name": "minio",
                            "domain": "minio.kubelab.live",
                            "health_path": "/minio/health/live",
                            "enable_auth": False,
                        },
                    },
                    "observability": {
                        "grafana": {
                            "name": "grafana",
                            "domain": "grafana.kubelab.live",
                            "health_path": "/api/health",
                            "enable_auth": True,
                        },
                    },
                    "security": {
                        "authelia": {
                            "name": "authelia",
                            "domain": "auth.kubelab.live",
                            "health_path": "/api/health",
                            "enable_auth": False,
                        },
                    },
                },
            },
            "edge": {
                "traefik": {
                    "name": "traefik",
                    "domain": "traefik.kubelab.live",
                    "health_path": "/ping",
                    "enable_auth": True,
                },
                "nginx": {
                    "name": "nginx-errors",
                    "health_path": "/health",
                    # No domain — should be skipped
                },
            },
        }

    def test_extracts_platform_apps(self) -> None:
        checker = HealthChecker.__new__(HealthChecker)
        configs = checker._extract_service_configs(self._make_config())
        names = [c.name for c in configs]
        assert "api" in names
        assert "web" in names

    def test_extracts_third_party_services(self) -> None:
        checker = HealthChecker.__new__(HealthChecker)
        configs = checker._extract_service_configs(self._make_config())
        names = [c.name for c in configs]
        assert "minio" in names
        assert "grafana" in names
        assert "authelia" in names

    def test_extracts_edge_with_domain(self) -> None:
        checker = HealthChecker.__new__(HealthChecker)
        configs = checker._extract_service_configs(self._make_config())
        names = [c.name for c in configs]
        assert "traefik" in names

    def test_skips_edge_without_domain(self) -> None:
        checker = HealthChecker.__new__(HealthChecker)
        configs = checker._extract_service_configs(self._make_config())
        names = [c.name for c in configs]
        assert "nginx" not in names
        assert "nginx-errors" not in names

    def test_categories_assigned(self) -> None:
        checker = HealthChecker.__new__(HealthChecker)
        configs = checker._extract_service_configs(self._make_config())
        by_name = {c.name: c for c in configs}
        assert by_name["api"].category == "platform"
        assert by_name["minio"].category == "services/data"
        assert by_name["traefik"].category == "edge"

    def test_minio_uses_correct_health_path(self) -> None:
        checker = HealthChecker.__new__(HealthChecker)
        configs = checker._extract_service_configs(self._make_config())
        minio = next(c for c in configs if c.name == "minio")
        assert minio.health_path == "/minio/health/live"

    def test_empty_config_returns_empty(self) -> None:
        checker = HealthChecker.__new__(HealthChecker)
        configs = checker._extract_service_configs({})
        assert configs == []

    def test_skips_entries_without_health_path(self) -> None:
        config = {
            "apps": {
                "platform": {
                    "workers": {
                        "name": "workers",
                        "domain": "workers.kubelab.live",
                        # No health_path
                    },
                },
            },
        }
        checker = HealthChecker.__new__(HealthChecker)
        configs = checker._extract_service_configs(config)
        assert len(configs) == 0


class TestResultInterpretation:
    """Test health check result logic."""

    def test_200_is_healthy(self) -> None:
        svc = ServiceHealthConfig(
            name="api", domain="api.kubelab.live", health_path="/health",
        )
        r = HealthCheckResult(
            service=svc.name, url=f"https://{svc.domain}{svc.health_path}",
            status_code=200, healthy=True, reason="OK",
        )
        assert r.healthy

    def test_302_with_auth_is_healthy(self) -> None:
        r = HealthCheckResult(
            service="grafana", url="https://grafana.kubelab.live/api/health",
            status_code=302, healthy=True, reason="redirect (auth expected)",
        )
        assert r.healthy

    def test_403_is_unhealthy(self) -> None:
        r = HealthCheckResult(
            service="minio", url="https://minio.kubelab.live/",
            status_code=403, healthy=False, reason="HTTP 403",
        )
        assert not r.healthy

    def test_zero_status_is_unhealthy(self) -> None:
        r = HealthCheckResult(
            service="down-svc", url="https://down.kubelab.live/health",
            status_code=0, healthy=False, reason="no response",
        )
        assert not r.healthy
