"""TOOL-035 (#1076) — the rotation registry and the Ansible mint tasks say the same thing.

`ROTATABLE_TOKENS` records each token's name in Gitea and its SOPS key. Both facts
are ALSO written in `beelink_services/tasks/main.yml`, which mints the tokens with
`--token-name <n>` and records them with `toolkit secrets set <key>`. Two
declarations of one truth, in two languages, neither able to import the other.

The right fix is a single declaration in `common.yaml` read by both. It is not
done yet because it edits a provisioning path that currently works and cannot be
exercised without a live re-provision of the Beelink. So the duplication stays and
this file makes it LOUD instead of latent: rename a token on either side, or add a
third one to Ansible alone, and this fails.

Matched by regex on the two flags rather than by parsing the YAML. The tasks are
dense with Jinja, and a `{{ ... }}` opening a plain scalar is not loadable YAML --
a structural parse would be the more precise tool and the more fragile one.

KNOWN AND DELIBERATE: the match is textual, so `--token-name x` written inside a
COMMENT trips it too. That direction of error is the cheap one -- a loud failure
on a line someone can move or reword. The opposite bias, quietly not matching a
real mint task, is the defect this file exists to prevent. If a comment ever does
trip it, reword the comment; do not loosen the pattern.

Verified by mutation on 2026-08-31, all three red: a typo in a registry token
name, a registry SOPS key Ansible never records, and a `--token-name` present in
the role with no registry entry.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from toolkit.features.gitea_tokens import ROTATABLE_TOKENS, format_rotation_plan, plan_rotation

TASKS = Path(__file__).resolve().parents[1] / "infra/ansible/roles/beelink_services/tasks/main.yml"

#: `--token-name kubelab-provisioning` -> the name Gitea stores the token under.
TOKEN_NAME_RE = re.compile(r"--token-name\s+(\S+)")
#: `toolkit secrets set apps.services.core.gitea.bot_token --env ...` -> the mint gate.
SECRETS_SET_RE = re.compile(r"toolkit secrets set\s+(\S+)")


@pytest.fixture(scope="module")
def tasks_text() -> str:
    assert TASKS.exists(), f"the beelink_services tasks moved: {TASKS}"
    return TASKS.read_text(encoding="utf-8")


def test_every_registered_token_name_is_minted_by_ansible(tasks_text: str) -> None:
    """A name only the registry knows would revoke nothing and report success.

    `revoke_token` treats a 404 as "already converged" -- correct for idempotence,
    and the reason a typo here is silent rather than loud. The guard has to live
    outside that call.
    """
    minted = set(TOKEN_NAME_RE.findall(tasks_text))
    registered = {spec.token_name for spec in ROTATABLE_TOKENS.values()}

    assert registered <= minted, (
        f"registry names not minted by Ansible: {sorted(registered - minted)}; the role mints {sorted(minted)}"
    )


def test_every_registered_secret_key_is_the_one_ansible_gates_on(tasks_text: str) -> None:
    """Clearing a key the mint task does not read leaves the gate shut.

    The token would be revoked, the wrong key cleared, and the next provision
    would mint nothing -- the stranded state, reached while reporting success.
    """
    recorded = set(SECRETS_SET_RE.findall(tasks_text))
    registered = {spec.secret_key for spec in ROTATABLE_TOKENS.values()}

    assert registered <= recorded, (
        f"registry keys Ansible never records: {sorted(registered - recorded)}; the role records {sorted(recorded)}"
    )


def test_ansible_mints_no_token_the_registry_cannot_rotate(tasks_text: str) -> None:
    """The reverse direction, and the one that rots quietly.

    A token added to the role alone is minted, lands in SOPS, and has no rotation
    path -- which is the exact defect this whole change was written to close, one
    credential later. Fail here rather than rediscover it.
    """
    minted = set(TOKEN_NAME_RE.findall(tasks_text))
    registered = {spec.token_name for spec in ROTATABLE_TOKENS.values()}

    assert minted <= registered, (
        f"Ansible mints tokens with no rotation path: {sorted(minted - registered)}. "
        "Add them to ROTATABLE_TOKENS in toolkit/features/gitea_tokens.py."
    )


def test_identities_resolve_through_the_map_not_a_literal() -> None:
    """AUTH-004 (#1390) removed the last hardcoded username; keep it removed.

    Storing `hefesto` in the registry would survive every test above and break
    silently the day the account is renamed.
    """
    identities = {"superadmin": "manu", "machine": "hefesto", "operator": "operator"}

    assert plan_rotation("bot", identities, secret_present=True).username == "hefesto"
    assert plan_rotation("admin", identities, secret_present=True).username == "manu"


def test_an_identity_missing_from_the_map_is_refused_not_guessed() -> None:
    """No fallback to a literal: a half-configured map must stop the rotation."""
    with pytest.raises(KeyError, match="machine"):
        plan_rotation("bot", {"superadmin": "manu"}, secret_present=True)


def test_an_unknown_token_label_names_the_known_ones() -> None:
    with pytest.raises(KeyError, match="admin, bot"):
        plan_rotation("nope", {"machine": "hefesto"}, secret_present=True)


def test_an_absent_secret_reports_the_gate_already_open() -> None:
    """`is_noop` is about the GATE, not about the forge.

    The token may well still be live; only the admin password can settle that.
    The plan says what it knows and no more.
    """
    plan = plan_rotation("bot", {"machine": "hefesto"}, secret_present=False)

    assert plan.is_noop
    assert "mint gate is already open" in format_rotation_plan(plan)
