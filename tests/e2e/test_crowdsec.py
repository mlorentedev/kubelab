"""E2E: CrowdSec bouncer and health tests."""

from __future__ import annotations

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

from .expectations import EXPECTATIONS

pytestmark = pytest.mark.e2e


class TestCrowdSecBouncer:
    """Verify CrowdSec bouncer is not blocking legitimate requests."""

    def test_normal_request_not_blocked(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        """A normal request should pass through the bouncer (not get 403)."""
        if env == "dev":
            pytest.skip("CrowdSec bouncer disabled in dev")

        # Pick a service that has CrowdSec bouncer in front
        svc = services_by_name.get("web")
        if not svc:
            pytest.skip("Web not in config")

        r = http_client_follow.get(f"https://{svc.domain}/")
        assert r.status_code != 403, (
            "Normal request was blocked by CrowdSec bouncer (403 Forbidden)"
        )

    def test_crowdsec_health(
        self,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        """CrowdSec dashboard/API should be reachable."""
        exp = EXPECTATIONS.get("crowdsec")
        if exp and env in exp.skip_in_envs:
            pytest.skip(f"CrowdSec skipped in {env}")

        svc = services_by_name.get("crowdsec")
        if not svc:
            pytest.skip("CrowdSec not in config")

        r = http_client.get(f"https://{svc.domain}{svc.health_path}")
        assert r.status_code in (200, 302), (
            f"CrowdSec health: expected 200/302, got {r.status_code}"
        )
