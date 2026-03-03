"""E2E: Content validation — parametrized over services with content expectations."""

from __future__ import annotations

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

from .expectations import EXPECTATIONS, ServiceExpectation

pytestmark = pytest.mark.e2e

# Filter services that have content expectations
_CONTENT_TYPE_SERVICES = sorted(k for k, v in EXPECTATIONS.items() if v.content_type)
_BODY_SERVICES = sorted(k for k, v in EXPECTATIONS.items() if v.body_contains)
_API_ENDPOINT_SERVICES = sorted(k for k, v in EXPECTATIONS.items() if v.api_endpoints)
_API_JSON_SERVICES = sorted(k for k, v in EXPECTATIONS.items() if v.api_json_keys)


def _resolve(
    svc_name: str,
    services_by_name: dict[str, ServiceHealthConfig],
    env: str,
) -> tuple[ServiceHealthConfig, ServiceExpectation]:
    exp = EXPECTATIONS[svc_name]
    if env in exp.skip_in_envs:
        pytest.skip(f"{svc_name} skipped in {env}")
    svc = services_by_name.get(svc_name)
    if not svc:
        pytest.skip(f"{svc_name} not in {env} config")
    return svc, exp


@pytest.mark.parametrize("svc_name", _CONTENT_TYPE_SERVICES)
class TestContentType:
    """Services must return the expected Content-Type."""

    def test_content_type_matches(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        svc, exp = _resolve(svc_name, services_by_name, env)
        r = http_client_follow.get(f"https://{svc.domain}/")

        ct = r.headers.get("content-type", "")
        assert exp.content_type in ct, (
            f"{svc_name}: expected content-type containing '{exp.content_type}', got '{ct}'"
        )


@pytest.mark.parametrize("svc_name", _BODY_SERVICES)
class TestBodyContent:
    """Services must contain expected content in their response body."""

    def test_body_contains_expected(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        svc, exp = _resolve(svc_name, services_by_name, env)
        r = http_client_follow.get(f"https://{svc.domain}/")

        assert exp.body_contains in r.text.lower(), (
            f"{svc_name}: expected '{exp.body_contains}' in body"
        )


@pytest.mark.parametrize("svc_name", _API_ENDPOINT_SERVICES)
class TestAPIEndpoints:
    """Services with API endpoints must return expected status codes."""

    def test_api_endpoints_respond(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc, exp = _resolve(svc_name, services_by_name, env)

        for path, expected_statuses in exp.api_endpoints.items():
            url = f"https://{svc.domain}{path}"
            r = http_client.get(url)
            assert r.status_code in expected_statuses, (
                f"{svc_name} {path}: expected {expected_statuses}, got {r.status_code}"
            )


@pytest.mark.parametrize("svc_name", _API_JSON_SERVICES)
class TestAPIJsonKeys:
    """Services with JSON APIs must return expected keys."""

    def test_api_json_contains_keys(
        self,
        svc_name: str,
        services_by_name: dict[str, ServiceHealthConfig],
        http_client: httpx.Client,
        env: str,
    ) -> None:
        svc, exp = _resolve(svc_name, services_by_name, env)

        for path, expected_keys in exp.api_json_keys.items():
            url = f"https://{svc.domain}{path}"
            r = http_client.get(url)

            if r.status_code in (302, 307, 401):
                pytest.skip(f"{svc_name} {path}: behind auth ({r.status_code})")

            assert r.status_code == 200, (
                f"{svc_name} {path}: expected 200, got {r.status_code}"
            )

            data = r.json()
            for key in expected_keys:
                assert key in data, f"{svc_name} {path}: missing key '{key}' in JSON response"
