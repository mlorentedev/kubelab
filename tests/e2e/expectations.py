"""E2E service expectations — the ONLY file to edit when adding/changing services.

Open/Closed: add a new service here, all tests pick it up automatically.
No test code changes needed.

IMPORTANT: Service names must match the keys in the merged YAML config
(common.yaml + env override), as extracted by HealthChecker._extract_service_configs().
Use underscores (grafana), not hyphens (grafana).
Run `make test-e2e` to verify names are correct — unmatched names show as skipped.
"""

from __future__ import annotations

import functools
import pathlib
import socket
from dataclasses import dataclass, field
from typing import Any

import yaml

#: Statuses Traefik returns for a route whose backend is not answering. 502 is
#: the direct case; 503/504 cover the no-available-server and timeout variants.
#: The error-pages middleware renders these, which is why they are the assertion
#: rather than an incidental detail.
OFFLINE_STATUS: tuple[int, ...] = (502, 503, 504)

_COMMON_YAML = pathlib.Path(__file__).resolve().parents[2] / "infra/config/values/common.yaml"


@functools.lru_cache(maxsize=1)
def _common_config() -> dict[str, Any]:
    """Load the SSOT. Never hardcode addresses in tests — see CLAUDE.md."""
    return yaml.safe_load(_COMMON_YAML.read_text())


def on_demand_target(svc_name: str, node_key: str) -> tuple[str, int]:
    """Resolve (tailscale_ip, port) for an on-demand-backed service from the SSOT.

    Both halves are looked up rather than written down: the address from
    `networking.nodes.<key>.tailscale_ip`, the port from the service's own
    `default_port` wherever it sits under `apps.services.*`.
    """
    cfg = _common_config()
    ip = cfg["networking"]["nodes"][node_key]["tailscale_ip"]

    for category in (cfg.get("apps", {}).get("services") or {}).values():
        if isinstance(category, dict) and svc_name in category:
            port = category[svc_name].get("default_port")
            if port:
                return str(ip), int(port)
    raise KeyError(f"{svc_name}: no apps.services.*.{svc_name}.default_port in common.yaml")


def backend_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    """TCP-probe the backend directly, bypassing the public route.

    Distinguishes "the node is powered off" from "the route is broken" — the
    whole point of the on-demand branch. A probe through the public domain
    could not tell those apart, since both surface as a 502.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


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
        on_demand_backend: `networking.nodes.<key>` of the on-demand node backing
            this service, for services fronted by an always-on Traefik but served
            from hardware that is deliberately powered off outside working hours
            (ADR-028 / ADR-061). Empty for everything else.

            This is NOT a way to make a service optional. The rest of the suite
            skips such a service when its node is unreachable — otherwise a
            powered-down homelab would report a prod outage — and
            `TestOnDemandBackend` then asserts the case that skipping would
            otherwise hide: with the backend down, the route, its TLS and its
            error-pages middleware must still be intact and answer 502/503/504.
            Both branches assert something real; neither can pass vacuously.
    """

    health_status: tuple[int, ...] = (200,)
    content_type: str | None = None
    body_contains: str | None = None
    auth_protected: bool = False
    unauthenticated_status: tuple[int, ...] = (302, 307, 401)
    api_endpoints: dict[str, tuple[int, ...]] = field(default_factory=dict)
    api_json_keys: dict[str, list[str]] = field(default_factory=dict)
    skip_in_envs: tuple[str, ...] = ()
    on_demand_backend: str = ""


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
    # -- Dashboard --
    # Homepage cockpit (DASH-001). Registered here after #967: home.kubelab.live was
    # advertised by the dashboard and by the DASH-001 docs but no prod route ever existed,
    # and nothing failed because the service had no entry at all.
    # NOTE: this entry cannot fail yet — there is no apps.services.*.homepage block with
    # domain + health_path in any values file, so _extract_service_configs() never yields
    # it and every env reports "homepage not in <env> config". CANNOT CHECK, not OK.
    "homepage": ServiceExpectation(
        content_type="text/html",
        body_contains="<html",
        auth_protected=False,  # Dashboard is unauthenticated — no Authelia middleware on the IngressRoute
        skip_in_envs=("dev",),  # Not in the dev Docker Compose stack (absent from dev.yaml)
    ),
    # -- Security --
    "authelia": ServiceExpectation(
        content_type="text/html",
    ),
    "crowdsec": ServiceExpectation(
        health_status=(200, 302),
        # LAPI is ClusterIP only, no public IngressRoute in either env. crowdsec.kubelab.live
        # holds a live Cloudflare record but returns 404 — a prod run would fail on a dead endpoint.
        skip_in_envs=("staging", "prod"),
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
        # staging: retired. Gitea is a singleton (ADR-061) — one instance, on the
        # prod apex name, backed by the Beelink.
        skip_in_envs=("staging",),
        # ...and that node is on-demand, so "prod is green" and "the homelab is
        # powered on" are now different statements. See TestOnDemandBackend.
        on_demand_backend="beelink",
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
    # -- AI / ML -- (empty since AI-007 retired Ollama; see ADR-029)
    # -- Network (bare-metal, external to K3s) --
    "pihole": ServiceExpectation(
        health_status=(200, 302),
        auth_protected=False,  # Pi-hole v6 has built-in auth (same pattern as n8n)
        content_type="text/html",
        # dev: not in the dev Docker Compose stack. prod: absence asserted by
        # tests/test_pihole_overlay_render.py, not by this e2e HTTP suite — the
        # apex name resolves to ace1's Tailscale IP regardless of what prod
        # ships, so no HTTP probe run against prod could ever see a regression
        # here (OPS-022, #969).
        skip_in_envs=("dev", "prod"),
    ),
    # -- Edge --
    # errors is Traefik's internal error page backend, not a user-facing service.
    # It has no public route — Traefik references it internally for custom 404/502 pages.
}


def on_demand_skip_reason(svc_name: str, exp: ServiceExpectation) -> str | None:
    """Why the ordinary suite should skip this service right now, or None.

    Returns a reason only when the service declares an on-demand backend AND
    that backend is unreachable. Everything else — including a reachable
    on-demand backend — is tested normally.
    """
    if not exp.on_demand_backend:
        return None
    host, port = on_demand_target(svc_name, exp.on_demand_backend)
    if backend_reachable(host, port):
        return None
    return (
        f"{svc_name}: on-demand backend {exp.on_demand_backend} ({host}:{port}) is "
        "powered off — the route itself is asserted by TestOnDemandBackend"
    )
