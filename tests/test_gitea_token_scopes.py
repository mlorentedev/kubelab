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


#: The methods without which the reconciler cannot do its job at all. An ANCHOR
#: against emptiness, deliberately NOT a restatement of `ADMIN_METHODS` — copying
#: the full tuple here would reintroduce the second declaration this file exists to
#: prevent, and a floor is enough to make vacuity impossible.
LOAD_BEARING_ADMIN_METHODS = frozenset({"list_orgs", "list_repos"})


def test_the_scope_guards_cannot_pass_by_being_empty() -> None:
    """GUARD THE GUARD, and check the DERIVED artefact rather than an upstream one.

    Measured by mutation on 2026-09-02: setting `ADMIN_METHODS = ()` left **all
    eight tests in this file green**. `REQUIRED_ADMIN_SCOPES` becomes the empty set,
    so `REQUIRED - expand_grant(...)` is empty, so the grant check is trivially
    satisfied — the entire scope apparatus switches off by emptying one tuple, and
    nothing says so.

    That is the same defect this file was written to cure, one level up. The file's
    thesis is "a check comparing a hand-written expectation against something that
    happens to match it proves nothing"; an empty expectation matches EVERYTHING,
    which is the strongest form of the same failure. It was found because a peer hit
    the identical shape in `test_traefik_ports_stay_behind_the_firewall.py` (#1565),
    where a derived set of exposed ports is empty and the ufw comparison is vacuous
    — and where the file's own anti-vacuity test passes, because it asserts the RAW
    render is populated rather than the DERIVED set.

    So this asserts on `REQUIRED_ADMIN_SCOPES` and `ADMIN_METHODS` themselves, which
    is what the other tests consume. Asserting that `SCOPE_BY_METHOD` is populated
    would repeat the peer's mistake exactly: it is one step upstream and stays full
    while the thing under test empties.
    """
    assert ADMIN_METHODS, (
        "ADMIN_METHODS is empty, so REQUIRED_ADMIN_SCOPES is the empty set and every scope check in "
        "this file passes against any grant whatsoever — including one that has been narrowed to "
        "nothing. An empty expectation matches everything."
    )
    assert REQUIRED_ADMIN_SCOPES, "REQUIRED_ADMIN_SCOPES is empty; the grant check cannot fail."

    missing = LOAD_BEARING_ADMIN_METHODS - set(ADMIN_METHODS)
    assert not missing, (
        f"ADMIN_METHODS no longer names {sorted(missing)}. The reconciler reads the forge with "
        f"those, so dropping one both breaks it and silently shrinks the requirement its own scope "
        f"guard checks. This is a floor, not a copy of the tuple — widening ADMIN_METHODS is "
        f"expected and does not fail here."
    )


def test_the_method_exhaustiveness_check_cannot_pass_by_being_empty() -> None:
    """The same trap on the other guard: no methods to check means nothing undeclared.

    `test_every_client_method_declares_the_scope_it_needs` computes `public` by
    introspecting `GiteaClient`. If that set were ever empty — a refactor moving the
    methods onto a mixin, a rename of the class — the subtraction yields nothing and
    the test reports success on a client whose scopes are entirely undeclared.
    """
    public = {
        name for name in vars(GiteaClient) if not name.startswith("_") and callable(getattr(GiteaClient, name, None))
    }
    assert len(public) >= len(LOAD_BEARING_ADMIN_METHODS), (
        f"introspection of GiteaClient found {sorted(public)}, which is too few to be the real "
        f"client. The exhaustiveness check subtracts this set from SCOPE_BY_METHOD, so an empty or "
        f"near-empty result makes it pass over a client that declares no scopes at all."
    )


def test_the_superadmin_token_is_never_granted_repository_writes(declared_scopes: dict[str, set[str]]) -> None:
    """`write:repository` on the ADMIN token would make deletion a standing capability. It must not.

    #1076 refuses deletion STRUCTURALLY — `ReconcilePlan` has no field one could
    travel in — and `drop-empty` keeps that intact by going through
    `GiteaBasicAuthClient`, an operator-triggered path with no token behind it.

    That arrangement has one soft spot, and this test is it. Measured 2026-09-02
    against live prod, `DELETE /repos/<owner>/<repo>` was refused three times, and
    the three refusals are NOT the same refusal:

        bot token             -> 403 "user should be the owner of the repo"
        admin token           -> 403 required=[write:repository]
        superadmin basic auth -> 204

    THE ASYMMETRY IS THE REASON THIS TEST NAMES ONLY ONE TOKEN. The bot already
    holds `write:repository` — it must, to create repositories at all — and is
    still refused, because deletion is additionally gated on repository ownership
    and ADR-065 D1 keeps the bot owning nothing. Scope is not the bot's last line
    of defence; ownership is. The superadmin's account IS a site admin, so for that
    token scope is the ONLY remaining gate, and the 403 it received is the entire
    thing standing between a reconciler credential and `DELETE` on any repository
    in the forge — populated ones included, since the `empty` guard is client-side
    and no credential consults it.

    So the obvious "fix" for anyone meeting that 403 — appending the scope here —
    is the one thing that must not happen quietly. The superset check in this file
    would not object: widening always passes. If a future caller genuinely needs
    superadmin repository writes, that is a decision taken deliberately against
    #1076's scope section, not a word added to a YAML string.
    """
    assert "write:repository" not in declared_scopes["admin"], (
        "the admin token's grant includes `write:repository`, which carries "
        "`DELETE /repos/<owner>/<repo>`. That account is a site admin, so this scope is the only "
        "gate left — granting it makes deletion a standing capability of the reconciler's own "
        "credential (#1076 refuses exactly that). `drop-empty` uses GiteaBasicAuthClient instead, "
        "so the power exists only for the duration of an operator-run command. If this was added "
        "to get past a 403 on a delete, that 403 was the design working."
    )


def test_basic_auth_methods_are_exempt_from_the_scope_map() -> None:
    """`GiteaBasicAuthClient` carries no token, so its methods declare no scope.

    Stated rather than left implicit, because `SCOPE_BY_METHOD` is checked for
    exhaustiveness against `GiteaClient` and a reader could reasonably wonder
    whether the subclass was forgotten. It was not: these endpoints reject bearer
    tokens before the handler runs (`reqBasicOrRevProxyAuth()` in Gitea's
    `routers/api/v1/api.go`), so a scope is not merely unnecessary, it is
    meaningless.
    """
    from toolkit.features.gitea_client import GiteaBasicAuthClient

    own = {name for name in vars(GiteaBasicAuthClient) if not name.startswith("_")}
    assert own, "GiteaBasicAuthClient defines no methods of its own — has it been refactored away?"
    assert not (own & set(SCOPE_BY_METHOD)), (
        f"{sorted(own & set(SCOPE_BY_METHOD))} appear in SCOPE_BY_METHOD but are basic-auth "
        f"methods. Declaring a scope for one implies a token path that does not exist, and would "
        f"drag that scope into REQUIRED_ADMIN_SCOPES if the method were ever added to ADMIN_METHODS."
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
