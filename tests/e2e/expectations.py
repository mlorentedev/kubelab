"""E2E service expectations — the ONLY file to edit when adding/changing services.

Open/Closed: add a new service here, all tests pick it up automatically.
No test code changes needed.

IMPORTANT: Service names must match the keys in the merged YAML config
(common.yaml + env override), as extracted by HealthChecker._extract_service_configs().
Use underscores (uptime_kuma), not hyphens (uptime-kuma).
Run `make test-e2e` to verify names are correct — unmatched names show as skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceExpectation:
    """Expected behavior for a deployed service.

    Attributes:
        health_status: Acceptable HTTP status codes for the health endpoint.
        content_type: Expected Content-Type prefix on the root page (None = skip check).
        body_contains: Substring expected in the response body (None = skip check).
        auth_protected: Whether unauthenticated requests should be rejected.
        unauthenticated_status: Acceptable status codes for unauthenticated requests
            to auth-protected services.
        api_endpoints: Additional endpoints to check — maps path to acceptable statuses.
        api_json_keys: Endpoints expected to return JSON with specific top-level keys.
        skip_in_envs: Environments where this service should be skipped entirely.
    """

    health_status: tuple[int, ...] = (200,)
    content_type: str | None = None
    body_contains: str | None = None
    auth_protected: bool = False
    unauthenticated_status: tuple[int, ...] = (302, 307, 401)
    api_endpoints: dict[str, tuple[int, ...]] = field(default_factory=dict)
    api_json_keys: dict[str, list[str]] = field(default_factory=dict)
    skip_in_envs: tuple[str, ...] = ()


# =============================================================================
# Service Expectations Registry
# =============================================================================
# To add a new service: add an entry here. All parametrized tests will
# automatically include it. No test file modifications needed.
#
# Names come from the YAML config keys (apps.platform.*, apps.services.*.*,
# edge.*). Verify with:
#   poetry run python -c "
#   from toolkit.features.configuration import ConfigurationManager
#   from toolkit.features.health_check import HealthChecker
#   cm = ConfigurationManager('dev')
#   checker = HealthChecker.__new__(HealthChecker)
#   for s in checker._extract_service_configs(cm.get_merged_config()):
#       print(s.name)
#   "

EXPECTATIONS: dict[str, ServiceExpectation] = {
    # -- Platform apps --
    "api": ServiceExpectation(
        api_endpoints={"/": (200, 301, 302, 404)},
        api_json_keys={"/health": ["status"]},
    ),
    "web": ServiceExpectation(
        content_type="text/html",
        body_contains="<html",
    ),
    "blog": ServiceExpectation(
        content_type="text/html",
        body_contains="<html",
    ),
    # -- Security --
    "authelia": ServiceExpectation(
        content_type="text/html",
    ),
    "crowdsec": ServiceExpectation(
        health_status=(200, 302),
        skip_in_envs=("staging",),  # LAPI is ClusterIP only, no public IngressRoute
    ),
    # -- Observability --
    "grafana": ServiceExpectation(
        health_status=(200, 302),
        auth_protected=True,
        api_json_keys={"/api/health": ["database"]},
    ),
    "loki": ServiceExpectation(
        health_status=(200, 302),
    ),
    "uptime_kuma": ServiceExpectation(
        health_status=(200, 302),
    ),
    # -- Core --
    "traefik": ServiceExpectation(
        health_status=(200, 302),
        auth_protected=True,
        api_endpoints={"/dashboard/": (200, 302, 401)},
        skip_in_envs=("staging",),  # Dashboard has no IngressRoute on K3s staging
    ),
    "portainer": ServiceExpectation(
        health_status=(200, 302, 307),
        api_json_keys={"/api/status": ["Version"]},
        skip_in_envs=("staging",),  # Docker Compose only, no K3s IngressRoute
    ),
    "gitea": ServiceExpectation(
        api_json_keys={"/api/v1/version": ["version"]},
    ),
    "n8n": ServiceExpectation(
        health_status=(200, 302),
        auth_protected=True,
    ),
    "headscale": ServiceExpectation(
        skip_in_envs=("dev",),  # VPN coordinator on VPS, not reachable from dev LAN
    ),
    # -- Data --
    "minio": ServiceExpectation(),
    # -- Edge --
    # errors is Traefik's internal error page backend, not a user-facing service.
    # It has no public route — Traefik references it internally for custom 404/502 pages.
}
