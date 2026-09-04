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
    VisibilityDrift,
    RepoSpec,
    actor_for_org_creation,
    actor_for_repo_creation,
    load_declaration,
    plan_reconcile,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: ADR-065 D2's provenance split, in the shape the reconciler consumes. `kubelab`
#: is declared while holding nothing, per D3 — an organization that exists only
#: because someone made it in the UI is state with no consumer.
#:
#: Every repository here carries a `migrate_from`, because all three are moves off
#: GitHub rather than new work. A `RepoSpec` without one is still legal and means
#: "create it empty" — that is what a genuinely new repository would look like.
DECLARED = {
    "teledyne": [
        RepoSpec("fae-brain", migrate_from="github:mlorentedev/fae-brain"),
        RepoSpec("openkm-brain", migrate_from="github:mlorentedev/openkm-brain"),
    ],
    "personal": [RepoSpec("resume", migrate_from="github:mlorentedev/resume")],
    "kubelab": [],
}


def test_an_empty_forge_migrates_every_declared_repository():
    """The shells are the bug this shape exists to prevent.

    PR1 declared repositories as bare names, so the only thing the reconciler could
    do with an absent one was create it EMPTY. All three were then blocked from
    ever receiving their content, because Gitea's `POST /repos/migrate` answers 409
    when the target exists — it creates a repository, it does not fill one. So a
    declaration that named a repository without saying where it comes from
    guaranteed the shell that blocked the move.
    """
    plan = plan_reconcile(DECLARED, existing_orgs=set(), existing_repos={})

    assert set(plan.orgs_to_create) == {"teledyne", "personal", "kubelab"}
    assert plan.repos_to_create == (), "a repository with a source must be migrated, never created empty"
    assert {(r.org, r.name, r.migrate_from) for r in plan.repos_to_migrate} == {
        ("teledyne", "fae-brain", "github:mlorentedev/fae-brain"),
        ("teledyne", "openkm-brain", "github:mlorentedev/openkm-brain"),
        ("personal", "resume", "github:mlorentedev/resume"),
    }


def test_a_repository_with_no_source_is_still_created_empty():
    """`migrate_from` is optional, and its absence means something specific.

    A genuinely new repository has nowhere to come from. Making the field required
    would force a fake source on the next repository that starts life in Gitea.
    """
    plan = plan_reconcile(
        {"kubelab": [RepoSpec("brand-new")]},
        existing_orgs={"kubelab"},
        existing_repos={},
    )
    assert plan.repos_to_migrate == ()
    assert {(r.org, r.name) for r in plan.repos_to_create} == {("kubelab", "brand-new")}


def test_an_existing_repository_is_never_re_migrated():
    """AC1's idempotence, on the path that would otherwise be destructive.

    Re-running a migration against a repository that already arrived is not a
    no-op the way a re-create is — Gitea answers 409, and a reconciler that
    treated that as "needs work" would report a permanent failure on a converged
    forge. Presence is presence, whatever put it there.
    """
    plan = plan_reconcile(
        DECLARED,
        existing_orgs=set(DECLARED),
        existing_repos={"teledyne/fae-brain": True, "teledyne/openkm-brain": True, "personal/resume": True},
    )
    assert plan.repos_to_migrate == ()
    assert plan.repos_to_create == ()
    assert plan.is_noop


def test_a_declared_but_empty_org_is_still_created():
    """ADR-065 D3: `kubelab` exists holding nothing, and that is deliberate.

    A reconciler that skipped empty organizations would leave D3 unimplementable
    and the declaration would quietly mean something else than it says.
    """
    plan = plan_reconcile({"kubelab": []}, existing_orgs=set(), existing_repos={})
    assert plan.orgs_to_create == ("kubelab",)


def test_a_second_run_creates_nothing():
    """AC1's idempotence, expressed where it can be tested without a forge."""
    existing_orgs = set(DECLARED)
    existing_repos = {f"{org}/{spec.name}": spec.private for org, specs in DECLARED.items() for spec in specs}

    plan = plan_reconcile(DECLARED, existing_orgs=existing_orgs, existing_repos=existing_repos)

    assert plan.orgs_to_create == ()
    assert plan.repos_to_create == ()


def test_an_undeclared_repository_is_reported():
    plan = plan_reconcile(
        DECLARED,
        existing_orgs=set(DECLARED),
        existing_repos={"personal/resume": True, "personal/something-nobody-declared": True},
    )
    assert plan.undeclared_repos == ("personal/something-nobody-declared",)


def test_an_undeclared_organization_is_reported():
    plan = plan_reconcile(
        DECLARED,
        existing_orgs=set(DECLARED) | {"made-in-the-ui"},
        existing_repos={},
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
def test_planning_never_reports_a_declared_org_as_undeclared(declared: dict[str, list[RepoSpec]]):
    """Guard the guard: a stray-detector that flags declared state is worse than none."""
    plan = plan_reconcile(declared, existing_orgs=set(declared), existing_repos={})
    assert plan.undeclared_orgs == ()


def test_declared_repos_carry_private_by_default():
    """A public repository on an internet-facing forge is the SEC-GITEA-001 shape.

    `REQUIRE_SIGNIN_VIEW` closes the anonymous surface, but defaulting to private
    means the forge does not depend on that one setting for confidentiality.
    """
    plan = plan_reconcile({"personal": [RepoSpec("resume")]}, existing_orgs={"personal"}, existing_repos={})
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

    assert {org: [s.name for s in specs] for org, specs in declared.items()} == {
        "teledyne": ["fae-brain", "openkm-brain"],
        "personal": ["resume"],
        "kubelab": [],
    }, "the declaration drifted from ADR-065's table — change the ADR or change the declaration"

    # Every declared repository is a MOVE off GitHub, not new work. A source that
    # went missing would silently turn a migration back into an empty shell -- the
    # exact regression this shape was introduced to end -- and nothing else would
    # look wrong, because creating a declared repository is a legitimate outcome.
    assert all(s.migrate_from for specs in declared.values() for s in specs), (
        "a declared repository lost its `migrate_from`. All three named by ADR-065 are migrations; "
        "without a source the reconciler would create an empty shell, which `POST /repos/migrate` "
        "then refuses with 409 -- the state this whole shape exists to prevent."
    )


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
    all_repos = {spec.name for specs in declared.values() for spec in specs}

    assert "knowledge" not in all_repos, (
        "`knowledge` is the vault. ADR-065 keeps it on GitHub because Gitea is on an "
        "on-demand node and this is the one repository whose loss is unrecoverable. "
        "Moving it is an ADR revision, not a declaration edit."
    )


def test_a_repository_living_at_a_different_visibility_is_reported():
    """The defect this comparison exists for, measured on prod 2026-09-03.

    All three declared repositories were living `private=False` while the
    declaration said nothing about visibility at all — so the default applied,
    the plan compared existence only, and `make gitea-reconcile` ended with
    "forge matches the declaration". Nothing was wrong with any individual check;
    the comparison simply never asked the question.
    """
    plan = plan_reconcile(
        {"personal": [RepoSpec("resume", private=True)]},
        existing_orgs={"personal"},
        existing_repos={"personal/resume": False},
    )
    assert plan.visibility_drift == (
        VisibilityDrift(org="personal", name="resume", declared_private=True, live_private=False),
    )


def test_drift_is_reported_in_both_directions():
    """Declared-public-but-live-private is drift too, and it is not the lesser case.

    A repository the declaration says is shared and the forge holds closed is a
    collaborator locked out, which reads as a permissions bug for as long as
    nobody compares the two. Asserting only the private->public direction would
    make this guard an alarm for one half of its own subject.
    """
    plan = plan_reconcile(
        {"personal": [RepoSpec("resume", private=False)]},
        existing_orgs={"personal"},
        existing_repos={"personal/resume": True},
    )
    assert [(d.full_name, d.declared_private, d.live_private) for d in plan.visibility_drift] == [
        ("personal/resume", False, True)
    ]


def test_a_matching_repository_is_not_reported_as_drift():
    """Guard the guard: a drift detector that fires on agreement is noise, not a check."""
    for private in (True, False):
        plan = plan_reconcile(
            {"personal": [RepoSpec("resume", private=private)]},
            existing_orgs={"personal"},
            existing_repos={"personal/resume": private},
        )
        assert plan.visibility_drift == (), f"agreement at private={private} was reported as drift"


def test_a_repository_that_does_not_exist_yet_is_not_drift():
    """It is in `repos_to_create` carrying its declared visibility.

    Reporting drift on something absent would report the plan back to itself, and
    would make every first run of a new declaration look like a divergence.
    """
    plan = plan_reconcile(
        {"personal": [RepoSpec("resume", private=False)]},
        existing_orgs={"personal"},
        existing_repos={},
    )
    assert plan.visibility_drift == ()
    assert plan.repos_to_create == (DeclaredRepo(org="personal", name="resume", private=False),)


def test_drift_does_not_make_the_plan_non_idempotent():
    """`is_noop` is about what would be DONE, and drift is never acted on.

    Folding it in would make a converged forge report work forever, which is how a
    real signal gets muted. The CLI says it separately instead — the noop branch
    warns rather than claiming a match.
    """
    plan = plan_reconcile(
        {"personal": [RepoSpec("resume", private=True)]},
        existing_orgs={"personal"},
        existing_repos={"personal/resume": False},
    )
    assert plan.visibility_drift, "fixture must actually drift or this asserts nothing"
    assert plan.is_noop


def test_the_plan_cannot_express_a_visibility_change():
    """Structural, the same reasoning as `test_the_plan_has_no_deletion_field`.

    Flipping a repository's visibility is a disclosure decision. A reconciler that
    made it silently on the strength of a YAML edit would be worse than one that
    reports. `VisibilityDrift` is a finding, so it must not grow a verb.
    """
    fields = {f.name for f in dataclasses.fields(VisibilityDrift)}
    offenders = {f for f in fields if any(v in f for v in ("apply", "fix", "set_", "change", "action"))}
    assert not offenders, (
        f"VisibilityDrift can express an action via {sorted(offenders)}. It is a report: "
        "visibility is changed by a human who decided to, never by a reconcile run."
    )


def test_the_declaration_and_the_forge_are_compared_on_every_declared_repo():
    """Anti-vacuity, on the value the assertion is actually made over.

    Lesson 416, third instance this week: a comparison over an empty set passes
    for every input. If `plan_reconcile` ever stopped populating this — a renamed
    field, an early return, a declaration shape it silently skips — every drift
    test above would keep passing while the comparison covered nothing. So assert
    the FLOOR on the derived output, not on the fixture that feeds it.
    """
    declared = {
        "personal": [RepoSpec("resume", private=False), RepoSpec("cv", private=True)],
        "teledyne": [RepoSpec("fae-brain", private=False)],
    }
    live = {"personal/resume": True, "personal/cv": True, "teledyne/fae-brain": True}

    plan = plan_reconcile(declared, existing_orgs=set(declared), existing_repos=live)

    compared = {d.full_name for d in plan.visibility_drift} | {
        f"{org}/{spec.name}"
        for org, specs in declared.items()
        for spec in specs
        if live.get(f"{org}/{spec.name}") == spec.private
    }
    assert compared == set(live), (
        "some declared-and-existing repository was neither reported as drift nor "
        f"matched: {set(live) - compared}. The comparison is not covering the declaration."
    )
