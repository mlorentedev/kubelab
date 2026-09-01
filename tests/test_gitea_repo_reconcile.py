"""TOOL-035 (#1076) — the reconciler plans creates, reports strays, and deletes nothing.

The planning half is pure on purpose. Everything that decides *what should happen*
takes two sets and returns a plan; everything that talks to Gitea takes a plan and
executes it. That split is what lets the dangerous property below be asserted
structurally rather than by hoping a code path is never reached.

The dangerous property, from #1076's own scope: "Deletion is **not** implicit. An
undeclared repository is reported, never removed — the blast radius of a
reconciler that deletes repositories is not one this needs to take on."

A test that merely checks "no delete was called" passes for a reconciler that has
a delete path nobody happened to trigger. So `test_the_plan_has_no_deletion_field`
asserts on the plan's *shape*: there is nowhere for a deletion to be expressed.
That holds for any future caller, which is the difference between a guard and a
fix (the same reasoning as `test_argocd_notification_triggers.py`).

Ownership comes from ADR-065 D1 and was measured live on 2026-08-27: the account
that creates an organization becomes the sole member of its `Owners` team. So the
credential used for organization creation is not an implementation detail — it is
the acceptance criterion, and it is asserted here rather than left to review.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from toolkit.features.gitea_repos import (
    Actor,
    DeclaredRepo,
    ReconcilePlan,
    actor_for_org_creation,
    actor_for_repo_creation,
    load_declaration,
    plan_reconcile,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: ADR-065 D2's provenance split, in the shape the reconciler consumes. `kubelab`
#: is declared while holding nothing, per D3 — an organization that exists only
#: because someone made it in the UI is state with no consumer.
DECLARED = {
    "teledyne": ["fae-brain", "openkm-brain"],
    "personal": ["resume"],
    "kubelab": [],
}


def test_an_empty_forge_gets_every_org_and_repo():
    plan = plan_reconcile(DECLARED, existing_orgs=set(), existing_repos=set())

    assert set(plan.orgs_to_create) == {"teledyne", "personal", "kubelab"}
    assert {(r.org, r.name) for r in plan.repos_to_create} == {
        ("teledyne", "fae-brain"),
        ("teledyne", "openkm-brain"),
        ("personal", "resume"),
    }


def test_a_declared_but_empty_org_is_still_created():
    """ADR-065 D3: `kubelab` exists holding nothing, and that is deliberate.

    A reconciler that skipped empty organizations would leave D3 unimplementable
    and the declaration would quietly mean something else than it says.
    """
    plan = plan_reconcile({"kubelab": []}, existing_orgs=set(), existing_repos=set())
    assert plan.orgs_to_create == ("kubelab",)


def test_a_second_run_creates_nothing():
    """AC1's idempotence, expressed where it can be tested without a forge."""
    existing_orgs = set(DECLARED)
    existing_repos = {f"{org}/{name}" for org, names in DECLARED.items() for name in names}

    plan = plan_reconcile(DECLARED, existing_orgs=existing_orgs, existing_repos=existing_repos)

    assert plan.orgs_to_create == ()
    assert plan.repos_to_create == ()


def test_an_undeclared_repository_is_reported():
    plan = plan_reconcile(
        DECLARED,
        existing_orgs=set(DECLARED),
        existing_repos={"personal/resume", "personal/something-nobody-declared"},
    )
    assert plan.undeclared_repos == ("personal/something-nobody-declared",)


def test_an_undeclared_organization_is_reported():
    plan = plan_reconcile(
        DECLARED,
        existing_orgs=set(DECLARED) | {"made-in-the-ui"},
        existing_repos=set(),
    )
    assert plan.undeclared_orgs == ("made-in-the-ui",)


def test_the_plan_has_no_deletion_field():
    """Structural, not behavioural — the point of #1076's "never removed".

    Asserting "no delete call happened" would pass for a reconciler that has a
    delete path this particular fixture did not reach. Asserting that the plan
    cannot EXPRESS a deletion holds for every caller, including ones not written
    yet. If someone later adds `orgs_to_delete`, this fails and they have to
    argue for it in review rather than discover it in prod.
    """
    fields = {f.name for f in dataclasses.fields(ReconcilePlan)}
    offenders = {f for f in fields if "delete" in f or "remove" in f or "prune" in f}
    assert not offenders, (
        f"ReconcilePlan can express a deletion via {sorted(offenders)}. #1076 scopes this "
        "reconciler to create-and-report: an undeclared repository is reported, never "
        "removed. The blast radius of a reconciler that deletes repositories is not one "
        "this takes on."
    )


def test_organizations_are_never_created_by_the_bot():
    """AC4 / ADR-065 D1, and it is measured rather than stylistic.

    Live on 2026-08-27: the account that creates an organization becomes the sole
    member of its `Owners` team. So creating orgs as the machine identity would
    make it an owner at the moment of creation, and D1's whole argument — that
    retiring the bot is a membership deletion, not a data migration — dies there.
    """
    assert actor_for_org_creation() is Actor.SUPERADMIN


def test_repositories_inside_an_org_are_created_by_the_bot():
    """The other half: the bot does the routine work it was minted for.

    Creating a repository INSIDE an organization confers no ownership of that
    organization, which is why widening the token to `write:organization` and
    keeping the bot ownerless are compatible — the contradiction ADR-065 appeared
    to carry.
    """
    assert actor_for_repo_creation() is Actor.MACHINE


@pytest.mark.parametrize("declared", [{}, {"only-org": []}])
def test_planning_never_reports_a_declared_org_as_undeclared(declared: dict[str, list[str]]):
    """Guard the guard: a stray-detector that flags declared state is worse than none."""
    plan = plan_reconcile(declared, existing_orgs=set(declared), existing_repos=set())
    assert plan.undeclared_orgs == ()


def test_declared_repos_carry_private_by_default():
    """A public repository on an internet-facing forge is the SEC-GITEA-001 shape.

    `REQUIRE_SIGNIN_VIEW` closes the anonymous surface, but defaulting to private
    means the forge does not depend on that one setting for confidentiality.
    """
    plan = plan_reconcile({"personal": ["resume"]}, existing_orgs={"personal"}, existing_repos=set())
    assert plan.repos_to_create == (DeclaredRepo(org="personal", name="resume", private=True),)


def test_the_real_declaration_matches_adr_065():
    """The SSOT in common.yaml, read by the same function the reconciler uses.

    Fixtures above prove the algorithm; this proves the *declaration* says what
    ADR-065 decided. Without it the two can drift silently -- a repository quietly
    dropped from `common.yaml` would leave every fixture green and simply stop
    being reconciled, which is the failure mode of a reconciler nobody notices.
    """
    import yaml

    common_yaml = REPO_ROOT / "infra/config/values/common.yaml"
    declared = load_declaration(yaml.safe_load(common_yaml.read_text()))

    assert declared == {
        "teledyne": ["fae-brain", "openkm-brain"],
        "personal": ["resume"],
        "kubelab": [],
    }, "the declaration drifted from ADR-065's table — change the ADR or change the declaration"


def test_the_vault_is_not_declared():
    """ADR-065 excludes `knowledge` deliberately, and the reason is load-bearing.

    It is the knowledge plane every session writes to, and Gitea runs on an
    on-demand node. A vault whose canonical remote is reachable only when the
    homelab is powered changes how the knowledge plane *works*, not merely where
    it is stored -- and it is the one repository whose loss is unrecoverable from
    anywhere else. Declaring it would be a one-line edit with no obvious tell,
    which is exactly why it gets a test rather than a comment.
    """
    import yaml

    common_yaml = REPO_ROOT / "infra/config/values/common.yaml"
    declared = load_declaration(yaml.safe_load(common_yaml.read_text()))
    all_repos = {name for names in declared.values() for name in names}

    assert "knowledge" not in all_repos, (
        "`knowledge` is the vault. ADR-065 keeps it on GitHub because Gitea is on an "
        "on-demand node and this is the one repository whose loss is unrecoverable. "
        "Moving it is an ADR revision, not a declaration edit."
    )
