"""E2E: the controls on Open WebUI's public name hold (#2135, ADR-068 amendment 2026-10-08).

`chat.kubelab.live` reaches Open WebUI on ace2 through prod Traefik. Three
controls make that name safe to publish, and until this file they were checked
once, by hand, at rollout. Nothing would have noticed a regression.

- The password form is refused at the edge. The break-glass account signs in
  with a password, and only over the tailnet.
- The OIDC login sends the browser to Authelia with the public callback, and
  Authelia accepts it. A drift between the client's registered redirect and
  the one Open WebUI sends refuses every SSO login.
- CORS echoes exactly the two declared origins, the public name and ace2's
  tailnet address.

The refusal is Traefik's, so it is asserted even with ace2 powered off. The
other two need Open WebUI to answer.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from tests.e2e.expectations import EXPECTATIONS, on_demand_skip_reason
from toolkit.features.health_check import ServiceHealthConfig

pytestmark = pytest.mark.e2e

SERVICE = "open_webui"


@pytest.fixture
def webui(env: str, services_by_name: dict[str, ServiceHealthConfig]) -> ServiceHealthConfig:
    if env in EXPECTATIONS[SERVICE].skip_in_envs:
        pytest.skip(f"{SERVICE} has no public route in {env}")
    svc = services_by_name.get(SERVICE)
    if not svc:
        pytest.fail(f"{SERVICE} is not in the {env} config, so its public controls went untested")
    return svc


@pytest.fixture
def webui_up(webui: ServiceHealthConfig) -> ServiceHealthConfig:
    reason = on_demand_skip_reason(SERVICE, EXPECTATIONS[SERVICE])
    if reason:
        pytest.skip(reason)
    return webui


def _settings(e2e_config: dict[str, Any]) -> dict[str, Any]:
    return e2e_config["apps"]["services"]["ai"]["open_webui"]


def test_the_password_form_is_refused_on_the_public_name(webui: ServiceHealthConfig, http_client: httpx.Client) -> None:
    r = http_client.post(f"https://{webui.domain}/api/v1/auths/signin", json={"email": "e2e@invalid", "password": "x"})
    assert r.status_code == 403, f"the public name let a password sign-in reach Open WebUI: {r.status_code}"


def test_the_oidc_login_sends_the_public_callback_and_authelia_accepts_it(
    webui_up: ServiceHealthConfig, http_client: httpx.Client, services_by_name: dict[str, ServiceHealthConfig]
) -> None:
    r = http_client.get(f"https://{webui_up.domain}/oauth/oidc/login")
    assert r.status_code in (302, 303, 307), f"no redirect to the IdP: {r.status_code}"
    target = urlparse(r.headers["location"])
    query = parse_qs(target.query)
    assert target.hostname == services_by_name["authelia"].domain
    assert query["redirect_uri"] == [f"https://{webui_up.domain}/oauth/oidc/callback"]

    # Authelia refuses an unregistered redirect with an error; an accepted one
    # goes on to its login flow.
    auth = http_client.get(r.headers["location"])
    assert auth.status_code in (302, 303), f"Authelia answered {auth.status_code} to the authorization request"
    landing = urlparse(auth.headers["location"])
    assert "error" not in parse_qs(landing.query), f"Authelia refused the request: {auth.headers['location']}"
    assert parse_qs(landing.query).get("flow") == ["openid_connect"], auth.headers["location"]


def test_cors_echoes_the_declared_origins_and_no_other(
    webui_up: ServiceHealthConfig, http_client: httpx.Client, e2e_config: dict[str, Any]
) -> None:
    cfg = _settings(e2e_config)
    declared = [f"https://{cfg['domain']}", f"{cfg['scheme']}://{cfg['host']}:{cfg['default_port']}"]

    def allowed(origin: str) -> str | None:
        r = http_client.get(f"https://{webui_up.domain}/api/config", headers={"Origin": origin})
        return r.headers.get("access-control-allow-origin")

    for origin in declared:
        assert allowed(origin) == origin, f"{origin} is declared and not allowed"
    assert allowed("https://not-declared.invalid") is None
