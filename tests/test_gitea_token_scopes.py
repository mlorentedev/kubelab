"""TOOL-035 (#1076) — a minted Gitea token's GRANT covers what its callers REQUIRE.

The grant is declared in `common.yaml` (`apps.services.core.gitea.token_scopes`)
because Ansible mints the tokens. The requirement is declared in Python, because
Python makes the calls. Neither language can import the other, so without this
file the two agree only by coincidence.

WHY THIS EXISTS, measured 2026-09-01. The admin token was minted with
`write:organization,read:repository`. Every signal said success: the mint task
reported `changed`, the value landed in prod SOPS, a key-name diff showed one key
added and none removed, and `secrets-audit` counted it present. Then:

    make gitea-reconcile ENV=prod
    GET /admin/orgs -> 403: token does not have at least one of required scope(s),
                            token scope=write:organization,read:repository

A credential that exists, authenticates, and cannot do its job. Same shape as
lesson-404 and as the Vikunja `VIKUNJA_FILES_S3_ENABLED` key that viper ignored
in silence: the question is never "did this value get set", it is "does anything
verify it does what it was set for". Presence checks answer the first question
and read as if they answered the second.

SUPERSET, NOT EQUALITY, and the choice is load-bearing. Equality would turn every
legitimate widening — a new capability needing a scope neither of these constants
knows about — into a failing test on a correct change, and a test that fails on
correct changes gets loosened. Superset fails on exactly the direction that
breaks things: a scope silently NARROWED out from under a caller that needs it.

Verified by mutation on 2026-09-01, all four red: dropping `read:admin` from the
admin grant, dropping `write:organization` from the bot grant, re-inlining a
literal scope string in the playbook, and adding a fifth entry to
`ROTATABLE_TOKENS` with no declared scope.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.gitea_client import (
    ADMIN_METHODS,
    REQUIRED_ADMIN_SCOPES,
    REQUIRED_BOT_SCOPE,
    SCOPE_BY_METHOD,
    GiteaClient,
    expand_grant,
)
from toolkit.features.gitea_tokens import ROTATABLE_TOKENS

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON = REPO_ROOT / "infra/config/values/common.yaml"
PLAYBOOK = REPO_ROOT / "infra/ansible/playbooks/provision-bee.yml"

#: `gitea_bot_scopes: "write:repository,..."` — a literal, which is the state this
#: whole file exists to prevent returning to. A Jinja lookup has no bare quote
#: after the colon, so the pattern only matches the inlined form.
INLINE_SCOPE_RE = re.compile(r"^\s*gitea_(?:bot|admin)_scopes:\s*[\"'][a-z]", re.MULTILINE)


@pytest.fixture(scope="module")
def declared_scopes() -> dict[str, set[str]]:
    """The grant, as sets — the comma-separated string is Gitea's wire format, not a contract."""
    assert COMMON.exists(), f"common.yaml moved: {COMMON}"
    config: Any = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    scopes = config["apps"]["services"]["core"]["gitea"]["token_scopes"]
    return {name: {s.strip() for s in value.split(",") if s.strip()} for name, value in scopes.items()}


def test_admin_grant_covers_what_the_reconciler_reads(declared_scopes: dict[str, set[str]]) -> None:
    """Without `read:admin` the reconciler cannot list organizations, and says so only at runtime.

    Imported, not copied — the same reasoning as the bot's scope below.
    `REQUIRED_ADMIN_SCOPES` is the client's own statement of what its calls need
    (`read:admin` for `list_orgs`, `write:organization` for `create_org`,
    `read:repository` for `list_repos`); restating that set here would be the
    second declaration the whole file exists to prevent.

    `/admin/orgs` is deliberate, not an oversight to route around: AC2's stray
    report is about organizations this account is NOT a member of, and
    `/user/orgs` would report an existing private org as absent.
    """
    missing = REQUIRED_ADMIN_SCOPES - expand_grant(declared_scopes["admin"])
    assert not missing, (
        f"the admin token's grant is missing {sorted(missing)}. It will still mint, still land in "
        f"SOPS and still pass secrets-audit — and `make gitea-reconcile` will 403. Widening this "
        f"is not enough on its own: Gitea cannot edit a minted token's scopes, so rotate "
        f"(`make gitea-rotate-token TOKEN=admin ENV=prod APPLY=1`) then re-provision."
    )


def test_bot_grant_covers_the_scope_its_client_declares(declared_scopes: dict[str, set[str]]) -> None:
    """Imported, not copied: `REQUIRED_BOT_SCOPE` is the client's own statement of need.

    Copying the string here would reproduce the exact defect the file guards —
    a requirement and a grant that agree only until one of them moves.
    """
    assert REQUIRED_BOT_SCOPE in declared_scopes["bot"], (
        f"gitea_client.REQUIRED_BOT_SCOPE is {REQUIRED_BOT_SCOPE!r}, which the bot's grant does not "
        f"include ({sorted(declared_scopes['bot'])}). Measured 2026-08-27: without it, creating a "
        f"repository inside an organization the bot does not own returns 403."
    )


def test_every_client_method_declares_the_scope_it_needs() -> None:
    """A method whose scope nobody declared is a capability nobody can grant.

    WHY THIS IS NOT THE SAME TEST AS THE TWO ABOVE. Those compare a REQUIREMENT
    against a GRANT, and they pass whenever the two agree — including when they
    agree about the wrong set. `REQUIRED_ADMIN_SCOPES` was hand-written by reading
    the code once, and the code moved: `whoami` and `list_owned_repos` were added
    to assert AC4 "by consequence", both call `/users/...`, both need `read:user`,
    and nothing anywhere said so. Measured 2026-09-02 against live prod:

        GET /users/hefesto        -> 403 required=[read:user], token scope=read:admin,...
        GET /users/hefesto/repos  -> 403 required=[read:user], token scope=read:admin,...
        GET /user                 -> 403 required=[read:user], token scope=read:admin,...

    So AC4 — "the bot owns nothing" — had a reader that could never read. Every
    other signal was green, which is lesson 413 arriving one layer up: last time
    the credential was present and powerless, this time the METHOD was present and
    powerless, and presence was mistaken for capability both times.

    The cure is to stop restating the requirement and start deriving it.
    `REQUIRED_ADMIN_SCOPES` is now a union over `SCOPE_BY_METHOD`, so a method
    cannot enter the client without its scope entering the grant's requirement.
    This test is what makes the map exhaustive: introspection over the class, so
    adding a method and forgetting the map fails here rather than at runtime in
    front of a forge.
    """
    public = {
        name
        for name in vars(GiteaClient)
        if not name.startswith("_") and callable(getattr(GiteaClient, name, None))
    }
    undeclared = public - set(SCOPE_BY_METHOD)
    assert not undeclared, (
        f"GiteaClient.{sorted(undeclared)} call the API with no entry in SCOPE_BY_METHOD. "
        f"Add one naming the scope Gitea demands — a method whose scope is undeclared is one "
        f"REQUIRED_ADMIN_SCOPES cannot cover, and it fails at runtime with a 403 that reads "
        f"like a permissions problem rather than a missing grant."
    )

    stale = set(SCOPE_BY_METHOD) - public
    assert not stale, (
        f"SCOPE_BY_METHOD names {sorted(stale)}, which GiteaClient no longer defines. A grant "
        f"kept alive for a deleted caller is scope granted for nothing."
    )


def test_the_admin_requirement_is_derived_from_the_methods_it_performs() -> None:
    """`REQUIRED_ADMIN_SCOPES` must stay a union over `ADMIN_METHODS`, never a second list.

    Re-inlining it as a literal frozenset is the shape this whole file exists to
    prevent, one level in: the grant would then be checked against a set that no
    longer tracks the code it describes — exactly how `read:user` went missing.
    """
    derived = frozenset().union(*(SCOPE_BY_METHOD[name] for name in ADMIN_METHODS))
    assert REQUIRED_ADMIN_SCOPES == derived, (
        f"REQUIRED_ADMIN_SCOPES is {sorted(REQUIRED_ADMIN_SCOPES)} but the methods the admin "
        f"credential performs need {sorted(derived)}. It has been restated instead of derived."
    )

    assert set(ADMIN_METHODS) <= set(SCOPE_BY_METHOD), (
        f"ADMIN_METHODS names {sorted(set(ADMIN_METHODS) - set(SCOPE_BY_METHOD))}, absent from "
        f"SCOPE_BY_METHOD."
    )


def test_every_rotatable_token_has_a_declared_scope(declared_scopes: dict[str, set[str]]) -> None:
    """A token that can be rotated but has no declared grant is re-minted with whatever the playbook guesses.

    The keys are aligned on purpose, so `TOKEN=admin` names the same credential in
    the rotation command and in the scope it comes back with.
    """
    undeclared = set(ROTATABLE_TOKENS) - set(declared_scopes)
    assert not undeclared, (
        f"{sorted(undeclared)} can be rotated but has no entry in "
        f"apps.services.core.gitea.token_scopes — rotation would revoke it and the re-mint would "
        f"have no grant to apply."
    )


def test_the_playbook_reads_the_ssot_instead_of_inlining_a_scope() -> None:
    """The SSOT only holds while the consumer actually reads it.

    Both grants were literals in this playbook until 2026-09-01. Re-inlining one
    would leave `common.yaml` looking authoritative while the mint used something
    else — the failure mode being cured, wearing the cure's clothes.
    """
    assert PLAYBOOK.exists(), f"the Beelink playbook moved: {PLAYBOOK}"
    inlined = INLINE_SCOPE_RE.findall(PLAYBOOK.read_text(encoding="utf-8"))
    assert not inlined, (
        f"{PLAYBOOK.name} inlines a token scope again: {inlined}. It must read "
        f"gitea_config.apps.services.core.gitea.token_scopes.<name>."
    )
