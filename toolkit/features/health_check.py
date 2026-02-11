"""Config-driven health checks for all services.

Reads health_path and domain from merged config (common.yaml + env overrides + secrets)
and checks each running service via curl.
"""

from typing import Any

from pydantic import BaseModel

from toolkit.config.constants import NETWORK_DEFAULTS
from toolkit.config.settings import get_settings
from toolkit.core.logging import logger
from toolkit.features import command
from toolkit.features.configuration import ConfigurationManager


class ServiceHealthConfig(BaseModel):
    """Health check configuration extracted from common.yaml."""

    name: str
    domain: str
    health_path: str
    enable_auth: bool = False
    category: str = ""


class HealthCheckResult(BaseModel):
    """Result of a single service health check."""

    service: str
    url: str
    status_code: int
    healthy: bool
    reason: str


class HealthChecker:
    """Checks service health using config-driven endpoints."""

    def __init__(self, env: str) -> None:
        self.env = env
        self.config_manager = ConfigurationManager(env)
        self.settings = get_settings(env)

    def _extract_service_configs(
        self, config: dict[str, Any]
    ) -> list[ServiceHealthConfig]:
        """Walk merged config tree and extract services with domain + health_path."""
        services: list[ServiceHealthConfig] = []

        # apps.platform.*
        platform = config.get("apps", {}).get("platform", {})
        for name, svc in platform.items():
            if isinstance(svc, dict) and svc.get("domain") and svc.get("health_path"):
                services.append(
                    ServiceHealthConfig(
                        name=name,
                        domain=svc["domain"],
                        health_path=svc["health_path"],
                        enable_auth=svc.get("enable_auth", False),
                        category="platform",
                    )
                )

        # apps.services.{category}.*
        svc_categories = config.get("apps", {}).get("services", {})
        for category, category_services in svc_categories.items():
            if not isinstance(category_services, dict):
                continue
            for name, svc in category_services.items():
                if (
                    isinstance(svc, dict)
                    and svc.get("domain")
                    and svc.get("health_path")
                ):
                    services.append(
                        ServiceHealthConfig(
                            name=name,
                            domain=svc["domain"],
                            health_path=svc["health_path"],
                            enable_auth=svc.get("enable_auth", False),
                            category=f"services/{category}",
                        )
                    )

        # edge.*
        edge = config.get("edge", {})
        for name, svc in edge.items():
            if isinstance(svc, dict) and svc.get("health_path"):
                domain = svc.get("domain", "")
                if domain:
                    services.append(
                        ServiceHealthConfig(
                            name=name,
                            domain=domain,
                            health_path=svc["health_path"],
                            enable_auth=svc.get("enable_auth", False),
                            category="edge",
                        )
                    )

        return services

    def _get_running_containers(self) -> set[str]:
        """Get names of currently running Docker containers."""
        try:
            result = command.run_list(
                ["docker", "ps", "--format", "{{.Names}}"],
                check=False,
            )
            if result.returncode != 0:
                return set()
            return {
                name.strip()
                for name in result.stdout.strip().split("\n")
                if name.strip()
            }
        except Exception:
            logger.warning("Docker not available")
            return set()

    def _check_service(
        self, svc: ServiceHealthConfig, protocol: str
    ) -> HealthCheckResult:
        """Check a single service health endpoint via curl."""
        url = f"{protocol}://{svc.domain}{svc.health_path}"
        timeout = str(NETWORK_DEFAULTS.CURL_TIMEOUT)

        try:
            result = command.run_list(
                [
                    "curl",
                    "-sk",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "--max-time",
                    timeout,
                    url,
                ],
                check=False,
            )
            status_code = (
                int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
            )
        except Exception:
            return HealthCheckResult(
                service=svc.name,
                url=url,
                status_code=0,
                healthy=False,
                reason="curl not available",
            )

        if status_code in (200, 204):
            return HealthCheckResult(
                service=svc.name,
                url=url,
                status_code=status_code,
                healthy=True,
                reason="OK",
            )

        if status_code in (301, 302):
            reason = "redirect (auth expected)" if svc.enable_auth else "redirect"
            return HealthCheckResult(
                service=svc.name,
                url=url,
                status_code=status_code,
                healthy=True,
                reason=reason,
            )

        return HealthCheckResult(
            service=svc.name,
            url=url,
            status_code=status_code,
            healthy=False,
            reason=f"HTTP {status_code}" if status_code else "no response",
        )

    def check_health(
        self, filter_names: list[str] | None = None
    ) -> list[HealthCheckResult]:
        """Check health of all (or filtered) running services.

        Args:
            filter_names: If provided, only check these service names.

        Returns:
            List of health check results.
        """
        config = self.config_manager.get_merged_config()
        all_services = self._extract_service_configs(config)

        if filter_names:
            filter_set = {n.lower() for n in filter_names}
            all_services = [s for s in all_services if s.name.lower() in filter_set]

        if not all_services:
            logger.warning("No services with health_path found in config.")
            return []

        protocol = self.settings.protocol

        running = self._get_running_containers()
        results: list[HealthCheckResult] = []

        for svc in all_services:
            # Check if the service container is running (loose match on name)
            container_running = any(svc.name in container for container in running)
            if not container_running and not filter_names:
                # Skip non-running services unless explicitly requested
                continue

            result = self._check_service(svc, protocol)
            results.append(result)

        return results
