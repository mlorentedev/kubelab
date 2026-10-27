"""E2E: Health endpoint tests — parametrized over all registered services."""

from __future__ import annotations

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

from .expectations import (
    EXPECTATIONS,
    OFFLINE_STATUS,
    BackendRefused,
    ServiceExpectation,
    backend_reachable,
    on_demand_skip_reason,
    on_demand_target,
)

pytestmark = pytest.mark.e2e


def _resolve(
    svc_name: str,
    services_by_name: dict[str, ServiceHealthConfig],
    env: str,
) -> tuple[ServiceHealthConfig, ServiceExpectation]:
    """Resolve service config + expectation, skip if not applicable."""
    exp = EXPECTATIONS[svc_name]
    if env in exp.skip_in_envs:
        pytest.skip(f"{svc_name} skipped in {env}")

    reason = on_demand_skip_reason(svc_name, exp)
    if reason:
        pytest.skip(reason)

    svc = services_by_name.get(svc_name)
    if not svc:
        pytest.skip(f"{svc_name} not in {env} config")

    return svc, exp


@pytest.mark.parametrize("svc_name", sorted(EXPECTATIONS.keys()))
class TestHealthEndpoint:
    """Every registered service must respond on its health path."""

    def test_health_returns_expected_status(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc, exp = _resolve(svc_name, services_by_name, env)
        url = f"https://{svc.domain}{svc.health_path}"

        try:
            r = http_client.get(url)
        except httpx.TimeoutException:
            pytest.fail(f"{svc_name} ({url}): timeout")

        assert r.status_code in exp.health_status, f"{svc_name}: expected {exp.health_status}, got {r.status_code}"


@pytest.mark.parametrize("svc_name", sorted(EXPECTATIONS.keys()))
class TestServiceReachable:
    """Every registered service must be reachable (no connection refused/timeout)."""

    def test_service_responds(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc, exp = _resolve(svc_name, services_by_name, env)
        url = f"https://{svc.domain}{svc.health_path}"

        try:
            http_client.get(url)
        except httpx.ConnectError:
            pytest.fail(f"{svc_name} ({url}): connection refused — check DNS and service status")
        except httpx.TimeoutException:
            pytest.fail(f"{svc_name} ({url}): timeout")


@pytest.mark.parametrize(
    "svc_name",
    sorted(n for n, e in EXPECTATIONS.items() if e.on_demand_backend),
)
class TestOnDemandBackend:
    """Services fronted by an always-on Traefik but served from on-demand hardware.

    This class exists because the rest of the suite *skips* these services when
    their node is powered off — necessary, since a powered-down homelab is not a
    prod outage, but on its own it would mean a whole service silently stops
    being tested for most of the week.

    So this runs unconditionally and branches:

    * backend up      → the service must actually answer, end to end.
    * backend silent  → the route, its certificate and its error-pages middleware
      must still be intact and return 502/503/504.
    * backend refuses → the node is up with the service down, an outage rather
      than an absence. The route must still return 502/503/504, as for a silent
      backend, and then this fails with the `BackendRefused` outage message.

    The offline branches are the valuable ones: they are exactly the states in which a
    deleted IngressRoute, an expired certificate or a broken middleware chain
    would otherwise go unnoticed, because nobody is looking while the lab is off.
    A flat `200 or 502` acceptance would cover both and assert nothing — the TCP
    probe is what makes the branch a real assertion rather than a wildcard.
    """

    def test_route_is_intact_whether_or_not_the_backend_is_up(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        exp = EXPECTATIONS[svc_name]
        if env in exp.skip_in_envs:
            pytest.skip(f"{svc_name} skipped in {env}")
        svc = services_by_name.get(svc_name)
        if not svc:
            pytest.skip(f"{svc_name} not in {env} config")

        host, port = on_demand_target(svc_name, exp.on_demand_backend)
        # A refusal is an outage, but it is also the window in which a broken route would go
        # unseen, so the route is asserted first and the refusal re-raised after it.
        refused: BackendRefused | None = None
        try:
            up = backend_reachable(host, port)
        except BackendRefused as exc:
            up, refused = False, exc
        backend = "is reachable" if up else "refuses connections" if refused is not None else "does not answer"
        outage = f" {refused}" if refused is not None else ""
        url = f"https://{svc.domain}{svc.health_path}"

        try:
            r = http_client.get(url)
        except httpx.TimeoutException:
            pytest.fail(
                f"{svc_name} ({url}): timeout. Backend {host}:{port} {backend} — a timeout at the "
                f"edge means the route, not the backend, since Traefik answers 502 for a dead service.{outage}"
            )

        if up:
            assert r.status_code in exp.health_status, (
                f"{svc_name}: backend {host}:{port} is up, so the public route must serve it — "
                f"expected {exp.health_status}, got {r.status_code}"
            )
        else:
            assert r.status_code in OFFLINE_STATUS, (
                f"{svc_name}: backend {host}:{port} {backend}, so Traefik must answer "
                f"{OFFLINE_STATUS} through error-pages — got {r.status_code}. "
                "Anything else means the route or its middleware chain is broken, "
                f"which is the failure this test exists to catch.{outage}"
            )
        if refused is not None:
            raise refused
