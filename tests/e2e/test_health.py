"""E2E: Health endpoint tests — parametrized over all registered services."""

from __future__ import annotations

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

from .expectations import EXPECTATIONS, ServiceExpectation

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

        assert r.status_code in exp.health_status, (
            f"{svc_name}: expected {exp.health_status}, got {r.status_code}"
        )


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
