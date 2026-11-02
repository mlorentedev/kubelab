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
    return yaml.safe_load(_COMMON_YAML.read_text(encoding="utf-8"))


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


class BackendRefused(AssertionError):
    """An on-demand backend's node answered and refused the connection.

    Raised, never returned, so a caller that forgets this case fails instead of
    reading "refused" as "down" and skipping, or as "up" and testing a dead service.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        super().__init__(
            f"the node is up and nothing is listening on {host}:{port} (connection refused). "
            "This is a service outage, not a powered-off node or a runner off the tailnet: "
            "check that the service is running and bound to that address on the node."
        )


def backend_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    """TCP-probe the backend directly, bypassing the public route.

    Distinguishes "the node is powered off" from "the route is broken" — the
    whole point of the on-demand branch. A probe through the public domain
    could not tell those apart, since both surface as a 502.

    Three outcomes, because a failed connection means two different things:

    * connected          → True.
    * nothing answered   → False. A timeout or no route: the node is off, or this
      runner is not on the tailnet. Neither is a service outage, so callers skip.
    * connection refused → raises `BackendRefused`. A refusal is an answer: the node
      is up and nothing is bound to the port (the Beelink after its 2026-08-14 reboot,
      Open WebUI on ace2, #2703). Skipping it reports a live outage as an absence.
      A runner off the tailnet never reaches the host, so it times out or finds no
      route rather than being refused.

    `tests/infra/test_network.py` makes the same cut, but for Gitea on the Beelink
    alone; this is the only check for every other on-demand backend.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except ConnectionRefusedError as exc:
        raise BackendRefused(host, port) from exc
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
            skips such a service when its node does not answer at all (timeout or
            no route) — otherwise a powered-down homelab would report a prod
            outage — and `TestOnDemandBackend` then asserts the case that skipping
            would otherwise hide: with the backend silent, the route, its TLS and
            its error-pages middleware must still be intact and answer 502/503/504.
            Both branches assert something real; neither can pass vacuously.
            A node that answers and *refuses* is neither: it is up with the
            service down. The check fails with `BackendRefused` when the route
            is intact; when the route is broken too, the outage is appended to
            the route's own failure.
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
    "uptime_kuma": ServiceExpectation(
        # #2483: the admin surface sits behind Authelia; status pages and the push
        # endpoint every node's backup heartbeat calls do not. A bad push token gets
        # Kuma's own 404, never a redirect to the portal.
        health_status=(200, 302),
        auth_protected=True,
        api_endpoints={"/api/entry-page": (200,), "/api/push/not-a-token": (404,)},
        skip_in_envs=("dev",),  # not behind Traefik in the dev Compose stack
    ),
    # -- Core --
    "traefik": ServiceExpectation(
        health_status=(200, 302),
        auth_protected=True,
        api_endpoints={"/dashboard/": (200, 302, 401)},
        skip_in_envs=("dev",),  # Dashboard exposed via IngressRoute in staging + prod with Authelia
    ),
    "gitea": ServiceExpectation(
        # SEC-GITEA-001 (#1389): /api/v1/version now returns 403 to anonymous
        # callers, and this suite is anonymous. /api/healthz is exempt from
        # REQUIRE_SIGNIN_VIEW and is the endpoint common.yaml declares as
        # `health_path` — so the probe now reads what the SSOT says instead of
        # a fifth literal copy of a path.
        api_json_keys={"/api/healthz": ["status"]},
        # staging: retired. Gitea is a singleton (ADR-061) — one instance, on the
        # prod apex name, backed by the Beelink.
        skip_in_envs=("staging",),
        # ...and that node is on-demand, so "prod is green" and "the homelab is
        # powered on" are now different statements. See TestOnDemandBackend.
        on_demand_backend="beelink",
    ),
    "open_webui": ServiceExpectation(
        # Its own OIDC login, not a ForwardAuth: anonymous /health answers 200.
        # Prod only, the one Authelia that registers its client (#2135).
        skip_in_envs=("dev", "staging"),
        # ace2 is the operator's on-demand developer node (ADR-068 D1).
        on_demand_backend="ace2",
    ),
    "n8n": ServiceExpectation(
        health_status=(200, 302),
        auth_protected=False,  # n8n 2.x has built-in auth; Authelia policy=bypass (OIDC is enterprise-only)
    ),
    "headscale": ServiceExpectation(
        skip_in_envs=("dev", "staging"),  # VPN on VPS only
    ),
    # -- Data -- (empty since OPS-023 retired the object store)
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


def skip_reason(svc_name: str, exp: ServiceExpectation, env: str) -> str | None:
    """Why the ordinary suite should skip this service in `env` right now, or None.

    The declaration is read before the probe. An env that never runs the service
    has no backend there, so a refusal from the node it targets elsewhere is not
    an outage of this env and must not fail it.
    """
    if env in exp.skip_in_envs:
        return f"{svc_name} skipped in {env}"
    return on_demand_skip_reason(svc_name, exp)


def on_demand_skip_reason(svc_name: str, exp: ServiceExpectation) -> str | None:
    """Why the ordinary suite should skip this service right now, or None.

    Returns a reason only when the service declares an on-demand backend AND
    that backend does not answer at all. Everything else — including a reachable
    on-demand backend — is tested normally. A backend that answers and refuses
    is not skipped: `backend_reachable` raises `BackendRefused`, which propagates,
    so a live outage cannot pass as an absence.
    """
    if not exp.on_demand_backend:
        return None
    host, port = on_demand_target(svc_name, exp.on_demand_backend)
    if backend_reachable(host, port):
        return None
    # Says what the probe measured: silence, with two causes it cannot tell apart.
    return (
        f"{svc_name}: on-demand backend {exp.on_demand_backend} did not answer on {host}:{port} "
        "(timeout: node off, or this runner is not on the tailnet) — "
        "the route itself is asserted by TestOnDemandBackend"
    )
