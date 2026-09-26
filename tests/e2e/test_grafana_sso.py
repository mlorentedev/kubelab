"""E2E: an SSO login to Grafana gives the declared tier (AUTH-004 AC2, #951).

Grafana's role is written from Authelia's `groups` at each OAuth login, and only
then. Every other e2e test reaches Grafana without logging in to it (`/api/health`
needs no session), so until this test nothing exercised the login that sets the
tier: the role path was verified by replaying its expression and by humans in a
browser.

The flow is the browser's: `/login/generic_oauth` redirects to Authelia, which
already holds the e2e session and, with `consent_mode: implicit` and a
`one_factor` policy on the `grafana` client, answers with a code at once. Grafana
exchanges it and opens its own session. The test then asks Grafana who it thinks
the user is and with which role.

A side effect, and the reason it was written when it was: the first run in an
environment links the e2e account to Generic OAuth. `make auth-review ENV=<env>`
shows that link, and the email-lookup migration flag can only come out once every
SSO identity has it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from toolkit.features.access_review import GrafanaTiers, declared_admins
from toolkit.features.health_check import ServiceHealthConfig

pytestmark = pytest.mark.e2e


@pytest.fixture
def grafana_sso(
    authenticated_client: httpx.Client | None,
    services_by_name: dict[str, ServiceHealthConfig],
    env: str,
) -> Iterator[tuple[httpx.Client, str]]:
    """A client holding only the Authelia session, logged in to Grafana through OAuth.

    Its own client, so the Grafana session it opens does not change what the other
    tests see through the shared one.
    """
    if authenticated_client is None:
        # This test is the only check of the login that sets the tier, so where the
        # e2e account exists a failed Authelia login must not read as green: a
        # rotated password or a brute-force lockout would otherwise skip it quietly.
        # The retired `ollama_api_key` fixture set the precedent (conftest.py).
        if env != "dev":
            pytest.fail(f"no Authelia session for the e2e account in {env}: the SSO login went untested")
        pytest.skip("No authenticated session (testuser not provisioned)")
    svc = services_by_name.get("grafana")
    if not svc:
        pytest.skip("Grafana not in config")

    client = httpx.Client(
        timeout=httpx.Timeout(20.0, connect=10.0),
        verify=env != "dev",
        follow_redirects=True,
        cookies=authenticated_client.cookies,
    )
    r = client.get(f"https://{svc.domain}/login/generic_oauth")
    hops = " -> ".join(f"{h.status_code} {h.url.host}{h.url.path}" for h in r.history)
    assert r.status_code == 200 and r.url.host == svc.domain, (
        f"the OAuth login did not land back on Grafana: {hops} -> {r.status_code} {r.url}"
    )
    assert "grafana_session" in client.cookies, f"Grafana opened no session after the OAuth round trip: {hops}"
    yield client, svc.domain
    client.close()


def test_sso_login_gives_the_declared_tier(
    grafana_sso: tuple[httpx.Client, str],
    authelia_test_credentials: tuple[str, str],
    e2e_config: dict[str, Any],
) -> None:
    client, domain = grafana_sso
    username = authelia_test_credentials[0]

    me = client.get(f"https://{domain}/api/user")
    assert me.status_code == 200, f"/api/user after the OAuth login: {me.status_code}"
    assert me.json()["login"] == username

    orgs = client.get(f"https://{domain}/api/user/orgs")
    assert orgs.status_code == 200, f"/api/user/orgs: {orgs.status_code}"
    want = GrafanaTiers.admin_tier if declared_admins(e2e_config)[username] else GrafanaTiers.user_tier
    roles = {o["name"]: o["role"] for o in orgs.json()}
    assert set(roles.values()) == {want}, f"{username} is declared {want}; Grafana gave {roles}"
