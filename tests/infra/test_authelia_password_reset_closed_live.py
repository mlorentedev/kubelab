"""Infrastructure: prod Authelia offers no self-service password reset, on the LIVE portal.

#1593 measured `POST /api/reset-password/identity/start` answering `200 {"status":"OK"}`
on `auth.kubelab.live`: an unauthenticated mail-send endpoint on a public host, aimed
at usernames this public repository declares in plaintext. #900 adds that the flow
could never finish anyway, because the user database is a read-only Secret mount.

The static half is `tests/test_authelia_password_reset_disabled.py`, which reads the
emitted ConfigMap for both environments. This half exists because a merged ConfigMap
is not a running pod (lesson-404, #1548).

Prod only, on purpose: `auth.staging.kubelab.live` is VPN-only split DNS, so nobody on
the internet can reach its reset endpoint, and the render test covers its manifest.

Probed with a username that does not exist. Authelia answers the same for known and
unknown users, so this tells enabled from disabled without mailing a real account.
"""

from __future__ import annotations

import os

import httpx
import pytest
import yaml

pytestmark = pytest.mark.infra

_PROD_YAML = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "infra/config/values/prod.yaml"))
RESET_START = "/api/reset-password/identity/start"
PROBE_USER = "kubelab-probe-nonexistent-9f2a"


def _prod_domain() -> str:
    with open(_PROD_YAML, encoding="utf-8") as handle:
        prod = yaml.safe_load(handle)
    return prod["apps"]["services"]["security"]["authelia"]["domain"]


@pytest.fixture(scope="module")
def base_url() -> str:
    url = f"https://{_prod_domain()}"
    try:
        health = httpx.get(f"{url}/api/health", timeout=15.0)
    except httpx.HTTPError as exc:
        pytest.skip(f"Authelia unreachable at {url} ({exc})")
    if health.status_code != 200:
        # A 502 through error-pages is neither 200 nor an open reset flow: without this
        # skip, both assertions would pass against an Authelia that is not running.
        pytest.skip(f"Authelia not healthy: /api/health returned {health.status_code}")
    return url


def test_the_portal_does_not_advertise_a_reset_link(base_url: str) -> None:
    page = httpx.get(f"{base_url}/", timeout=15.0).text
    assert 'data-resetpassword="' in page, (
        "the portal no longer carries `data-resetpassword`: Authelia may have renamed it. "
        "Fix this guard before reading its result as a finding."
    )
    assert 'data-resetpassword="false"' in page, "the portal still renders the 'Reset password?' link"


def test_the_reset_endpoint_no_longer_starts_a_reset(base_url: str) -> None:
    response = httpx.post(
        f"{base_url}{RESET_START}", json={"username": PROBE_USER}, timeout=15.0, follow_redirects=False
    )
    opened = response.status_code == 200 and response.headers.get("content-type", "").startswith("application/json")
    assert not (opened and response.json().get("status") == "OK"), (
        f"POST {RESET_START} answered 200 OK: the reset flow is still live. Check that the running "
        "pod reads a ConfigMap with `authentication_backend.password_reset.disable: true`."
    )
