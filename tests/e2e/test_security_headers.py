"""E2E: Security header validation — parametrized over services with Traefik-managed headers."""

from __future__ import annotations

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

from .expectations import EXPECTATIONS

pytestmark = pytest.mark.e2e

# Services that manage their own headers (skip Traefik header checks)
_SELF_MANAGED_HEADERS = {"authelia", "headscale", "crowdsec"}

_HEADER_SERVICES = sorted(
    k for k in EXPECTATIONS if k not in _SELF_MANAGED_HEADERS
)

# Expected security headers from Traefik secure-headers middleware
_EXPECTED_HEADERS = {
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
}

_HSTS_HEADER = "strict-transport-security"
_HSTS_MIN_MAX_AGE = 31536000


@pytest.mark.parametrize("svc_name", _HEADER_SERVICES)
class TestSecurityHeaders:
    """Traefik-fronted services must include standard security headers."""

    def test_security_headers_present(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        exp = EXPECTATIONS[svc_name]
        if env in exp.skip_in_envs:
            pytest.skip(f"{svc_name} skipped in {env}")

        svc = services_by_name.get(svc_name)
        if not svc:
            pytest.skip(f"{svc_name} not in {env} config")

        r = http_client_follow.get(f"https://{svc.domain}{svc.health_path}")

        errors: list[str] = []
        for header, expected_value in _EXPECTED_HEADERS.items():
            actual = r.headers.get(header, "")
            if expected_value.lower() not in actual.lower():
                errors.append(
                    f"{header}: expected '{expected_value}', got '{actual or '(missing)'}'"
                )

        if errors:
            if env == "dev":
                pytest.skip(
                    f"{svc_name}: security headers not enforced in dev — {errors}"
                )
            pytest.fail(f"{svc_name} security header failures:\n" + "\n".join(errors))

    def test_hsts_header(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        if env == "dev":
            pytest.skip("HSTS not enforced in dev (self-signed certs)")

        exp = EXPECTATIONS[svc_name]
        if env in exp.skip_in_envs:
            pytest.skip(f"{svc_name} skipped in {env}")

        svc = services_by_name.get(svc_name)
        if not svc:
            pytest.skip(f"{svc_name} not in {env} config")

        # Use non-follow client: auth-protected services redirect to Authelia,
        # and the redirect response (from Traefik) carries the HSTS header.
        r = http_client.get(f"https://{svc.domain}{svc.health_path}")

        hsts = r.headers.get(_HSTS_HEADER, "")
        assert "max-age=" in hsts, (
            f"{svc_name}: missing or invalid HSTS header: '{hsts or '(missing)'}'"
        )

        # Extract max-age value and verify minimum
        for part in hsts.split(";"):
            part = part.strip()
            if part.startswith("max-age="):
                max_age = int(part.split("=")[1])
                assert max_age >= _HSTS_MIN_MAX_AGE, (
                    f"{svc_name}: HSTS max-age={max_age}, expected >= {_HSTS_MIN_MAX_AGE}"
                )
                break

        assert "includesubdomains" in hsts.lower(), (
            f"{svc_name}: HSTS missing includeSubDomains"
        )
