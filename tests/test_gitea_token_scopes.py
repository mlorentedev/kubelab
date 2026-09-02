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

from toolkit.features.gitea_client import REQUIRED_BOT_SCOPE
from toolkit.features.gitea_tokens import ROTATABLE_TOKENS

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON = REPO_ROOT / "infra/config/values/common.yaml"
PLAYBOOK = REPO_ROOT / "infra/ansible/playbooks/provision-bee.yml"

#: What `toolkit.features.gitea_client.GiteaClient` needs before the reconciler's
#: READS work, one entry per endpoint that refused without it:
#:   read:admin         -> GET /admin/orgs      (list_orgs; measured 403 above)
#:   write:organization -> POST /orgs           (create_org)
#:   read:repository    -> GET /repos/search    (list_repos)
#: Not imported from the client the way `REQUIRED_BOT_SCOPE` is, because no such
#: constant exists there yet — declaring one is the client owner's call, and this
#: set is the interim home for the measurement rather than a second opinion about
#: it. If `REQUIRED_ADMIN_SCOPES` ever lands in `gitea_client`, import it and
#: delete this.
REQUIRED_ADMIN_SCOPES = frozenset({"read:admin", "write:organization", "read:repository"})

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

    `/admin/orgs` is deliberate, not an oversight to route around: AC2's stray
    report is about organizations this account is NOT a member of, and
    `/user/orgs` would report an existing private org as absent.
    """
    missing = REQUIRED_ADMIN_SCOPES - declared_scopes["admin"]
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
