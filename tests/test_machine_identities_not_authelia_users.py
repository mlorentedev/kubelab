"""No machine identity is an Authelia user, so none of them can sign in interactively (#2504).

AUTH-004 AC5 wants `hefesto` (and `mentor`, the reviewer) unable to log in while
their scoped tokens keep working. Gitea cannot give both: `prohibit_login` also
kills API tokens (measured on 1.25.5, AUTH-004 verification "R4 addendum"). So
the block is that neither account holds a credential anyone can use at the IdP,
which is true only while neither is declared in
`apps.services.security.authelia.users`. That was an omission nothing enforced.
This test makes it a rule, in every environment.

Every entry is resolved through `resolve_user_identity`, the one resolver both
user-database generators call, so an entry that names the identity by key
(`identity: machine`) and one that spells the username literally are both caught.

The live half, a refused first factor on prod, is
`tests/infra/test_machine_identities_refused_live.py`.
"""

from __future__ import annotations

import pytest

from toolkit.features.configuration import ConfigurationManager, resolve_user_identity

ENVS = ("dev", "staging", "prod")

#: Keys of `apps.auth.identities` that name a machine, not a person.
MACHINE_IDENTITY_KEYS = ("machine", "reviewer")


def _config(env: str) -> dict:
    return ConfigurationManager(env).get_plaintext_values()


@pytest.mark.parametrize("env", ENVS)
def test_the_machine_identity_keys_are_declared(env: str) -> None:
    """A renamed key would make the check below compare against nothing and pass."""
    identities = _config(env)["apps"]["auth"]["identities"]
    for key in MACHINE_IDENTITY_KEYS:
        assert identities.get(key), f"apps.auth.identities.{key} is not declared in {env}"


@pytest.mark.parametrize("env", ENVS)
def test_no_machine_identity_is_an_authelia_user(env: str) -> None:
    config = _config(env)
    identities = config["apps"]["auth"]["identities"]
    machines = {identities[key] for key in MACHINE_IDENTITY_KEYS}
    users = config["apps"]["services"]["security"]["authelia"].get("users") or []
    declared = {resolve_user_identity(user, config) for user in users}
    assert not machines & declared, (
        f"{env}: {sorted(machines & declared)} would get an Authelia password and could sign in "
        "interactively; machine identities authenticate with scoped tokens only (#2504)"
    )
