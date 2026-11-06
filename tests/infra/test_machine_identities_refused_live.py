"""Infrastructure: prod Authelia refuses a first factor for each machine identity (#2504).

The static half, `tests/test_machine_identities_not_authelia_users.py`, holds the
declaration. This half records the refusal on the running portal, because AUTH-004
asked for a demonstration rather than an absence.

A refusal here cannot tell an unknown account from a bad credential: Authelia
answers both with the same 401, on purpose. The password is random, so the test shows
that the first factor fails, not why. The static half shows why.

One attempt per identity per run. Prod bans a username after 3 failures in 2
minutes (`regulation`), and CrowdSec reads the same failures. A third run inside
2 minutes bans the machine username for 5 minutes. That costs nothing, since
neither account ever signs in. It bans no address: `regulation` sets no `modes`,
and Authelia's default is `['user']` (configuration/security/regulation).
"""

from __future__ import annotations

import os
import secrets

import httpx
import pytest
import yaml

from toolkit.features.configuration import ConfigurationManager

pytestmark = pytest.mark.infra

_VALUES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "infra/config/values"))
FIRST_FACTOR = "/api/firstfactor"
MACHINE_IDENTITY_KEYS = ("machine", "reviewer")


def _load(name: str) -> dict:
    with open(os.path.join(_VALUES, name), encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _machine_usernames() -> list[str]:
    # The merged prod config, as the static half reads it: an override in
    # prod.yaml must change the name probed here too.
    identities = ConfigurationManager("prod").get_plaintext_values()["apps"]["auth"]["identities"]
    return [identities[key] for key in MACHINE_IDENTITY_KEYS]


@pytest.fixture(scope="module")
def base_url() -> str:
    url = f"https://{_load('prod.yaml')['apps']['services']['security']['authelia']['domain']}"
    try:
        health = httpx.get(f"{url}/api/health", timeout=15.0)
    except httpx.HTTPError as exc:
        pytest.skip(f"Authelia unreachable at {url} ({exc})")
    if health.status_code != 200:
        # A 502 through error-pages also "refuses": without this skip the test
        # would pass against an Authelia that is not running.
        pytest.skip(f"Authelia not healthy: /api/health returned {health.status_code}")
    return url


@pytest.mark.parametrize("username", _machine_usernames())
def test_a_first_factor_as_a_machine_identity_is_refused(base_url: str, username: str) -> None:
    response = httpx.post(
        f"{base_url}{FIRST_FACTOR}",
        json={"username": username, "password": secrets.token_urlsafe(24), "keepMeLoggedIn": False},
        timeout=15.0,
        follow_redirects=False,
    )
    assert response.status_code == 401, f"{username}: first factor answered {response.status_code}"
    assert response.json().get("status") == "KO", response.text
