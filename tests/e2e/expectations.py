"""E2E service expectations — the ONLY file to edit when adding/changing services.

Open/Closed: add a new service here, all tests pick it up automatically.
No test code changes needed.

IMPORTANT: Service names must match the keys in the merged YAML config
(common.yaml + env override), as extracted by HealthChecker._extract_service_configs().
Use underscores (grafana), not hyphens (grafana).
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
    # blog: removed 2026-03-15
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
        skip_in_envs=("prod",),  # Internal-only in prod (no public IngressRoute)
    ),
    # -- Core --
    "traefik": ServiceExpectation(
        health_status=(200, 302),
        auth_protected=True,
        api_endpoints={"/dashboard/": (200, 302, 401)},
        skip_in_envs=("dev",),  # Dashboard exposed via IngressRoute in staging + prod with Authelia
    ),
    "gitea": ServiceExpectation(
        api_json_keys={"/api/v1/version": ["version"]},
    ),
    "n8n": ServiceExpectation(
        health_status=(200, 302),
        auth_protected=False,  # n8n 2.x has built-in auth; Authelia policy=bypass (OIDC is enterprise-only)
    ),
    "headscale": ServiceExpectation(
        skip_in_envs=("dev", "staging"),  # VPN on VPS only
    ),
    # -- Data --
    "minio": ServiceExpectation(),
    # -- AI / ML --
    "ollama": ServiceExpectation(
        api_json_keys={"/api/tags": ["models"]},
        skip_in_envs=("dev", "prod"),  # Bare metal on Beelink, reachable only via VPN (staging)
    ),
    # -- Network (bare-metal, external to K3s) --
    "pihole": ServiceExpectation(
        health_status=(200, 302),
        auth_protected=False,  # Pi-hole v6 has built-in auth (same pattern as n8n)
        content_type="text/html",
        skip_in_envs=("dev",),  # RPi4 bare metal, reachable via VPN (staging) + Tailscale (prod)
    ),
    # -- Edge --
    # errors is Traefik's internal error page backend, not a user-facing service.
    # It has no public route — Traefik references it internally for custom 404/502 pages.
}
