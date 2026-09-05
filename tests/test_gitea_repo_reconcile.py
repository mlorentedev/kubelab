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
import yaml

from toolkit.features.gitea_client import TEAM_UNITS
from toolkit.features.gitea_repos import (
    TEAM_NAME,
    TEAM_PERMISSION,
    Actor,
    DeclaredRepo,
    ReconcilePlan,
    RepoSettings,
    RepoSpec,
    VisibilityDrift,
    actor_for_org_creation,
    actor_for_repo_creation,
    load_declaration,
    load_settings,
    plan_reconcile,
    settings_needs_convergence,
    team_needs_convergence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: What `GET /repos/{owner}/{repo}` returned for ALL THREE declared repositories on
#: 2026-09-04, transcribed rather than constructed. This is the fixture that stands
#: for Gitea, so it must not be derived from `RepoSettings` -- a "live" body built
#: by calling `to_api_payload()` would agree with our field names by construction
#: and could never catch us having invented one (lesson-423).
GITEA_MIGRATION_DEFAULTS: dict[str, object] = {
    "default_merge_style": "merge",
    "has_pull_requests": True,
    "allow_merge_commits": True,
    "allow_squash_merge": True,
    "allow_rebase": True,
    "allow_rebase_explicit": True,
    "allow_fast_forward_only_merge": True,
    "default_delete_branch_after_merge": False,
    "has_wiki": True,
    "has_projects": True,
    # Present in the live body and deliberately NOT declared: act_runner needs it.
    "has_actions": True,
    "default_branch": "main",
}

#: The declaration under test. Read from common.yaml rather than restated, so these
#: tests measure what the forge will actually be given -- a literal here would let
#: the SSOT and the suite drift, which is the whole failure mode this file is about.
DECLARED_SETTINGS = load_settings(yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text()))


def converged_body() -> dict[str, object]:
    """A live repository body that already satisfies the declaration.

    DERIVED from the declaration, like `converged_team` is derived from
    `TEAM_UNITS`: restating it would make the fixture agree with itself. The floor
    under the derivation is `test_the_settings_fixtures_are_what_they_claim`, which
    checks the OTHER fixture -- the measured one -- genuinely disagrees.

    Carries the undeclared live keys too, so a comparison that wrongly ranged over
    the whole body instead of over the declared fields would be caught here.
    """
    return {
        **GITEA_MIGRATION_DEFAULTS,
        **DECLARED_SETTINGS.to_api_payload(),
    }


def settings_for(declared: object) -> dict[str, dict[str, object] | None]:
    """Every declared repository, already converged.

    The default for tests about something else, exactly as `converged_for` is for
    teams: without it every one of them would report settings work it was never
    written to assert. Tests about settings build their own mapping.
    """
    return {
        f"{org}/{spec.name}": converged_body()
        for org, specs in declared.items()  # type: ignore[attr-defined]
        for spec in specs
    }


def converged_team() -> dict[str, object]:
    """A team holding exactly the grant `create_team` sends, DERIVED from `TEAM_UNITS`.

    Restating the units here would make this fixture agree with itself rather than
    with the payload — the failure lesson-423 is about, one layer up.

    `permission` is `"none"` on purpose: that is what a CORRECT team reads back as,
    because the grant lives per unit. See `GiteaClient.create_team`.
    """
    return {
        "id": 7,
        "name": TEAM_NAME,
        "permission": "none",
        "can_create_org_repo": True,
        "units_map": {unit: TEAM_PERMISSION for unit in TEAM_UNITS},
        "includes_all_repositories": True,
    }


def converged_for(declared: object) -> dict[str, dict[str, object]]:
    """Every declared organization, holding a converged team.

    The default for tests that are about repositories rather than teams: without
    it every one of them would report team work it was never written to assert.
    Tests about teams build their own mapping.
    """
    return {org: converged_team() for org in declared}  # type: ignore[attr-defined]


def test_the_converged_fixture_is_actually_converged() -> None:
    """The floor under every `converged_for` in this file.

    If `converged_team` drifted from the grant — a unit added to `TEAM_UNITS` and
    not to the fixture, a field renamed — every test using it would start reporting
    a team to converge, and the ones asserting `is_noop` would fail loudly while the
    rest would pass for a changed reason. This says so in one place, against the
    predicate itself rather than against a copy of its rules.
    """
    assert not team_needs_convergence(converged_team())
    assert team_needs_convergence(None), "an absent team must need convergence, or nothing is ever created"


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
    plan = plan_reconcile(DECLARED, existing_orgs=set(), existing_repos={}, existing_teams=converged_for(DECLARED), existing_repo_settings=settings_for(DECLARED), declared_settings=DECLARED_SETTINGS)

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
        existing_teams=converged_for({"kubelab": [RepoSpec("brand-new")]}),
        existing_repo_settings=settings_for({"kubelab": [RepoSpec("brand-new")]}), declared_settings=DECLARED_SETTINGS)
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
        existing_teams=converged_for(DECLARED),
        existing_repo_settings=settings_for(DECLARED), declared_settings=DECLARED_SETTINGS)
    assert plan.repos_to_migrate == ()
    assert plan.repos_to_create == ()
    assert plan.is_noop


def test_a_declared_but_empty_org_is_still_created():
    """ADR-065 D3: `kubelab` exists holding nothing, and that is deliberate.

    A reconciler that skipped empty organizations would leave D3 unimplementable
    and the declaration would quietly mean something else than it says.
    """
    plan = plan_reconcile(
        {"kubelab": []}, existing_orgs=set(), existing_repos={}, existing_teams=converged_for({"kubelab": []}),
        existing_repo_settings=settings_for({"kubelab": []}), declared_settings=DECLARED_SETTINGS)
    assert plan.orgs_to_create == ("kubelab",)


def test_a_second_run_creates_nothing():
    """AC1's idempotence, expressed where it can be tested without a forge."""
    existing_orgs = set(DECLARED)
    existing_repos = {f"{org}/{spec.name}": spec.private for org, specs in DECLARED.items() for spec in specs}

    plan = plan_reconcile(
        DECLARED, existing_orgs=existing_orgs, existing_repos=existing_repos, existing_teams=converged_for(DECLARED),
        existing_repo_settings=settings_for(DECLARED), declared_settings=DECLARED_SETTINGS)

    assert plan.orgs_to_create == ()
    assert plan.repos_to_create == ()


def test_an_undeclared_repository_is_reported():
    plan = plan_reconcile(
        DECLARED,
        existing_orgs=set(DECLARED),
        existing_repos={"personal/resume": True, "personal/something-nobody-declared": True},
        existing_teams=converged_for(DECLARED),
        existing_repo_settings=settings_for(DECLARED), declared_settings=DECLARED_SETTINGS)
    assert plan.undeclared_repos == ("personal/something-nobody-declared",)


def test_an_undeclared_organization_is_reported():
    plan = plan_reconcile(
        DECLARED,
        existing_orgs=set(DECLARED) | {"made-in-the-ui"},
        existing_repos={},
        existing_teams=converged_for(DECLARED),
        existing_repo_settings=settings_for(DECLARED), declared_settings=DECLARED_SETTINGS)
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
    plan = plan_reconcile(
        declared, existing_orgs=set(declared), existing_repos={}, existing_teams=converged_for(declared),
        existing_repo_settings=settings_for(declared), declared_settings=DECLARED_SETTINGS)
    assert plan.undeclared_orgs == ()


def test_declared_repos_carry_private_by_default():
    """A public repository on an internet-facing forge is the SEC-GITEA-001 shape.

    `REQUIRE_SIGNIN_VIEW` closes the anonymous surface, but defaulting to private
    means the forge does not depend on that one setting for confidentiality.
    """
    plan = plan_reconcile(
        {"personal": [RepoSpec("resume")]},
        existing_orgs={"personal"},
        existing_repos={},
        existing_teams=converged_for({"personal": [RepoSpec("resume")]}),
        existing_repo_settings=settings_for({"personal": [RepoSpec("resume")]}), declared_settings=DECLARED_SETTINGS)
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
        existing_teams=converged_for({"personal": [RepoSpec("resume", private=True)]}),
        existing_repo_settings=settings_for({"personal": [RepoSpec("resume", private=True)]}), declared_settings=DECLARED_SETTINGS)
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
        existing_teams=converged_for({"personal": [RepoSpec("resume", private=False)]}),
        existing_repo_settings=settings_for({"personal": [RepoSpec("resume", private=False)]}), declared_settings=DECLARED_SETTINGS)
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
            existing_teams=converged_for({"personal": [RepoSpec("resume", private=private)]}),
        existing_repo_settings=settings_for({"personal": [RepoSpec("resume", private=private)]}), declared_settings=DECLARED_SETTINGS)
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
        existing_teams=converged_for({"personal": [RepoSpec("resume", private=False)]}),
        existing_repo_settings=settings_for({"personal": [RepoSpec("resume", private=False)]}), declared_settings=DECLARED_SETTINGS)
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
        existing_teams=converged_for({"personal": [RepoSpec("resume", private=True)]}),
        existing_repo_settings=settings_for({"personal": [RepoSpec("resume", private=True)]}), declared_settings=DECLARED_SETTINGS)
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

    plan = plan_reconcile(
        declared, existing_orgs=set(declared), existing_repos=live, existing_teams=converged_for(declared),
        existing_repo_settings=settings_for(declared), declared_settings=DECLARED_SETTINGS)

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


# =============================================================================
# Team convergence — the grant belongs to the organization, not to the creation
# =============================================================================
#
# Measured on prod 2026-09-03, AFTER the fix that added `includes_all_repositories`
# to `create_team` merged green: both live `reconcilers` teams still covered zero
# repositories. `execute` only ever visited the organizations RECEIVING a new
# repository, every declared repository already existed, so the set was empty --
# and the CLI returned at `is_noop` before `execute` ran at all. The repair was
# correct, tested, merged, and unreachable.
#
# The class, stated once: A CONVERGENCE STEP SCOPED TO THE CREATION DIFF NEVER
# REPAIRS WHAT ALREADY EXISTS.


def _narrow_team() -> dict[str, object]:
    """A team in the exact state both live teams were measured in.

    Every field-level check `ensure_team` makes passes on this. It grants
    `repo.code -> write` over nothing.
    """
    return {**converged_team(), "includes_all_repositories": False}


def test_a_forge_with_nothing_to_create_still_plans_a_team_repair() -> None:
    """The measured production state, as a test.

    Every declared repository present, every organization present, one team narrow.
    Before this, the plan was `is_noop` and the CLI printed "forge matches the
    declaration" -- while the bot could push to nothing.
    """
    declared = {"personal": [RepoSpec("resume", private=False)]}

    plan = plan_reconcile(
        declared,
        existing_orgs={"personal"},
        existing_repos={"personal/resume": False},
        existing_teams={"personal": _narrow_team()},
        existing_repo_settings=settings_for(declared), declared_settings=DECLARED_SETTINGS)

    assert plan.repos_to_create == () and plan.repos_to_migrate == () and plan.orgs_to_create == ()
    assert plan.teams_to_converge == ("personal",)
    assert not plan.is_noop, (
        "a plan carrying a team repair reported itself as a no-op, so the CLI returns before "
        "`execute` is ever called. That is how a merged, tested repair stayed unreachable."
    )


def test_a_team_is_planned_for_a_declared_org_that_receives_no_repository() -> None:
    """The grant belongs to the organization, not to the act of creating in it.

    `kubelab` is declared holding nothing (ADR-065 D3). Under the old scoping it
    could never get a team, because nothing was ever created inside it.
    """
    plan = plan_reconcile(
        {"kubelab": []},
        existing_orgs={"kubelab"},
        existing_repos={},
        existing_teams={"kubelab": None},
        existing_repo_settings=settings_for({"kubelab": []}), declared_settings=DECLARED_SETTINGS)

    assert plan.teams_to_converge == ("kubelab",)


def test_converged_teams_leave_the_plan_a_noop() -> None:
    """The control. Without it every assertion above passes for a plan that always converges."""
    plan = plan_reconcile(
        DECLARED,
        existing_orgs=set(DECLARED),
        existing_repos={"teledyne/fae-brain": True, "teledyne/openkm-brain": True, "personal/resume": True},
        existing_teams=converged_for(DECLARED),
        existing_repo_settings=settings_for(DECLARED), declared_settings=DECLARED_SETTINGS)

    assert plan.teams_to_converge == ()
    assert plan.is_noop


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"includes_all_repositories": False}, id="covers-no-repository"),
        pytest.param({"can_create_org_repo": False}, id="cannot-create"),
        pytest.param({"units_map": {"repo.code": "read"}}, id="cannot-push"),
        pytest.param({"units_map": {}}, id="no-units-at-all"),
    ],
)
def test_every_field_the_grant_sends_is_compared(broken: dict[str, object]) -> None:
    """A predicate covering a subset of the grant is the same defect one field over.

    `ensure_team` raises on each of these. If the plan called such a team converged,
    `is_noop` would be True, the CLI would return, and the reconcile would report a
    match on a team it would have refused had it looked -- which is the shape of
    every finding in this area.
    """
    declared = {"personal": [RepoSpec("resume")]}

    plan = plan_reconcile(
        declared,
        existing_orgs={"personal"},
        existing_repos={"personal/resume": True},
        existing_teams={"personal": {**converged_team(), **broken}},
        existing_repo_settings=settings_for(declared), declared_settings=DECLARED_SETTINGS)

    assert plan.teams_to_converge == ("personal",), f"a team with {broken} was reported as converged"


def test_a_declared_org_missing_from_the_team_reading_is_a_loud_failure() -> None:
    """Incompleteness raises rather than reading as converged.

    The alternative -- `existing_teams.get(org)` -- would make a declaration the
    caller forgot to read teams for look fully converged, which is the failure this
    whole change is about, reintroduced through the door marked "convenience".
    """
    with pytest.raises(KeyError):
        plan_reconcile(
            DECLARED,
            existing_orgs=set(DECLARED),
            existing_repos={},
            existing_teams={"personal": converged_team()},
        existing_repo_settings=settings_for(DECLARED), declared_settings=DECLARED_SETTINGS)


def test_the_plan_compares_a_team_for_every_declared_organization() -> None:
    """Anti-vacuity on the derived value, not on the fixture that feeds it.

    Lesson 416. If `plan_reconcile` stopped iterating the declaration -- an early
    return, a renamed field, a filter that silently excludes -- `teams_to_converge`
    would go empty and every assertion above would still pass. So make one run in
    which EVERY declared organization must appear, and check the output covers the
    declaration rather than checking the input.
    """
    plan = plan_reconcile(
        DECLARED,
        existing_orgs=set(DECLARED),
        existing_repos={"teledyne/fae-brain": True, "teledyne/openkm-brain": True, "personal/resume": True},
        existing_teams={org: _narrow_team() for org in DECLARED},
        existing_repo_settings=settings_for(DECLARED), declared_settings=DECLARED_SETTINGS)

    assert set(plan.teams_to_converge) == set(DECLARED), (
        "the plan did not consider a team for every declared organization: "
        f"missing {set(DECLARED) - set(plan.teams_to_converge)}"
    )


# ---------------------------------------------------------------------------
# Repository settings (TOOL-063, #1633)
#
# Settings do not survive `POST /repos/migrate`, and Gitea's defaults are
# permissive — so a migrated repository does not arrive unconfigured, it arrives
# configured more weakly. The first shows up as an empty field; the second reads
# as a working repository, which is why it needed a ticket rather than a glance.
# ---------------------------------------------------------------------------


def test_the_settings_fixtures_are_what_they_claim() -> None:
    """THE FLOOR UNDER EVERY `settings_for` AND `GITEA_MIGRATION_DEFAULTS` BELOW.

    Two halves, and both are needed (lesson-416: an empty expectation is not a weak
    expectation, it matches everything):

    - the CONVERGED fixture must genuinely satisfy the declaration, or every test
      using it as a background would be reporting settings work it never asserted;
    - the MEASURED fixture must genuinely fall short, or every drift test below
      would be passing over a repository that needed nothing.

    The second is the one that would rot silently. `converged_body()` is derived
    from the declaration and so can never disagree with it; `GITEA_MIGRATION_DEFAULTS`
    is an independent transcription, and if the declaration were ever weakened to
    match Gitea's defaults the drift tests would quietly stop testing anything.
    """
    assert not settings_needs_convergence(converged_body(), DECLARED_SETTINGS)
    assert settings_needs_convergence(GITEA_MIGRATION_DEFAULTS, DECLARED_SETTINGS), (
        "the declaration no longer differs from what a migrated repository arrives with, "
        "so every drift test in this file is now vacuous"
    )


def test_every_declared_field_is_a_field_gitea_actually_returns() -> None:
    """The names are Gitea's, not ours — asserted against a transcribed live body.

    A declaration field Gitea does not know is not a new setting: it is a key the
    PATCH carries and the forge ignores, after which the repository can never
    converge and every run reports the same drift as success-then-failure forever.

    Checked against `GITEA_MIGRATION_DEFAULTS`, which was copied out of a live
    `GET /repos/{owner}/{repo}` on 2026-09-04. Comparing the dataclass to itself —
    or to a fixture built from it — would certify our belief instead of testing it
    (lesson-423).
    """
    unknown = set(DECLARED_SETTINGS.to_api_payload()) - set(GITEA_MIGRATION_DEFAULTS)
    assert unknown == set(), f"declared field(s) {sorted(unknown)} are not in Gitea's repository body"


def test_actions_are_never_declared_off() -> None:
    """`has_actions` must stay out of the declaration.

    act_runner needs it, and TOOL-035 AC6 only just got CI green on this forge
    (personal/resume#260, six of six jobs). A declaration that turned it off would
    take that down as a side effect of a merge-style change, and the reconciler
    would report it as a successful convergence.
    """
    assert "has_actions" not in DECLARED_SETTINGS.to_api_payload()
    assert GITEA_MIGRATION_DEFAULTS["has_actions"] is True, "the live fixture no longer models Actions being on"


def test_the_ssot_declares_squash_only() -> None:
    """What #1633 was filed to fix, asserted on the declaration the forge is handed.

    Read from common.yaml rather than restated: a test that hardcoded `squash` would
    pass while the SSOT said something else, which is the exact gap between "a
    setting is declared" and "the forge is given it".
    """
    assert DECLARED_SETTINGS.default_merge_style == "squash"
    assert DECLARED_SETTINGS.allow_squash_merge is True
    assert not any(
        (
            DECLARED_SETTINGS.allow_merge_commits,
            DECLARED_SETTINGS.allow_rebase,
            DECLARED_SETTINGS.allow_rebase_explicit,
            DECLARED_SETTINGS.allow_fast_forward_only_merge,
        )
    ), "another merge style is still allowed; squash-only is not squash-plus-whatever"


def test_a_migrated_repository_is_scheduled_for_configuration() -> None:
    """The state prod was measured in on 2026-09-04, on all three repositories."""
    declared = {"personal": [RepoSpec("resume", migrate_from="github:mlorentedev/resume")]}
    plan = plan_reconcile(
        declared,
        existing_orgs={"personal"},
        existing_repos={"personal/resume": True},
        existing_teams=converged_for(declared),
        existing_repo_settings={"personal/resume": GITEA_MIGRATION_DEFAULTS},
        declared_settings=DECLARED_SETTINGS,
    )

    assert [change.full_name for change in plan.repos_to_configure] == ["personal/resume"]
    assert not plan.is_noop, "a forge whose merge settings drift has work to do"
    assert plan.repos_to_create == () and plan.repos_to_migrate == ()


def test_a_repository_this_run_creates_is_scheduled_in_the_same_run() -> None:
    """lesson-424 read backwards: a step scoped to what EXISTS never reaches what this run makes.

    A new repository arrives with Gitea's permissive defaults, so it needs
    configuring immediately — not on some later run that happens to notice.
    """
    declared = {"personal": [RepoSpec("brand-new")]}
    plan = plan_reconcile(
        declared,
        existing_orgs={"personal"},
        existing_repos={},
        existing_teams=converged_for(declared),
        existing_repo_settings={"personal/brand-new": None},
        declared_settings=DECLARED_SETTINGS,
    )

    assert [change.full_name for change in plan.repos_to_configure] == ["personal/brand-new"]
    assert plan.repos_to_configure[0].absent is True
    assert [r.name for r in plan.repos_to_create] == ["brand-new"]


def test_a_converged_repository_schedules_nothing() -> None:
    """AC1's idempotence on the settings path: a second run must be a no-op."""
    declared = {"personal": [RepoSpec("resume")]}
    plan = plan_reconcile(
        declared,
        existing_orgs={"personal"},
        existing_repos={"personal/resume": True},
        existing_teams=converged_for(declared),
        existing_repo_settings={"personal/resume": converged_body()},
        declared_settings=DECLARED_SETTINGS,
    )

    assert plan.repos_to_configure == ()
    assert plan.is_noop


@pytest.mark.parametrize("field_name", sorted(DECLARED_SETTINGS.to_api_payload()))
def test_every_declared_field_is_compared(field_name: str) -> None:
    """One field wrong is enough, for every field.

    A predicate covering a SUBSET of the declaration is the same defect one field
    over: the plan reports a match, the CLI exits at `is_noop`, and the field stays
    wrong forever. This is the settings twin of
    `test_every_field_the_grant_sends_is_compared`, and it is parametrised over the
    declaration itself so a field added to `RepoSettings` cannot arrive without a
    case.
    """
    declared_value = DECLARED_SETTINGS.to_api_payload()[field_name]
    wrong = "not-a-merge-style" if isinstance(declared_value, str) else not declared_value
    live = {**converged_body(), field_name: wrong}

    assert settings_needs_convergence(live, DECLARED_SETTINGS), f"{field_name} is declared but never compared"


def test_a_declared_repository_missing_from_the_settings_reading_is_a_loud_failure() -> None:
    """Incompleteness raises rather than reading as convergence.

    The same contract as `existing_teams` and `existing_repos`: a caller that
    supplies a partial mapping has failed to read the forge, and treating a missing
    key as "fine" is how a comparison silently stops comparing.
    """
    declared = {"personal": [RepoSpec("resume"), RepoSpec("other")]}
    with pytest.raises(KeyError):
        plan_reconcile(
            declared,
            existing_orgs={"personal"},
            existing_repos={"personal/resume": True, "personal/other": True},
            existing_teams=converged_for(declared),
            existing_repo_settings={"personal/resume": converged_body()},
            declared_settings=DECLARED_SETTINGS,
        )


def test_the_plan_names_the_fields_that_will_change() -> None:
    """The printed plan is what `--apply` is approved on.

    `~ settings personal/resume` says nothing an operator can weigh.
    `default_merge_style: 'merge' -> 'squash'` says all of it.
    """
    from toolkit.features.gitea_repos import format_plan

    declared = {"personal": [RepoSpec("resume")]}
    plan = plan_reconcile(
        declared,
        existing_orgs={"personal"},
        existing_repos={"personal/resume": True},
        existing_teams=converged_for(declared),
        existing_repo_settings={"personal/resume": GITEA_MIGRATION_DEFAULTS},
        declared_settings=DECLARED_SETTINGS,
    )
    rendered = format_plan(plan)

    assert "default_merge_style" in rendered
    assert "'merge' -> 'squash'" in rendered
    assert "personal/resume" in rendered


def test_a_new_repository_is_summarised_rather_than_diffed() -> None:
    """Nine `None -> x` lines would bury the one repository that actually drifted."""
    from toolkit.features.gitea_repos import format_plan

    declared = {"personal": [RepoSpec("brand-new")]}
    plan = plan_reconcile(
        declared,
        existing_orgs={"personal"},
        existing_repos={},
        existing_teams=converged_for(declared),
        existing_repo_settings={"personal/brand-new": None},
        declared_settings=DECLARED_SETTINGS,
    )
    rendered = format_plan(plan)

    assert "new repository" in rendered
    assert "None ->" not in rendered


def test_an_absent_settings_block_is_refused_rather_than_defaulted() -> None:
    """The blind spot this loader exists to close.

    Mirroring `load_declaration`'s absent-is-empty would mean "compare nothing" —
    switching the check off on every repository, silently. And a DEFAULT would be
    worse than the absence: it would have to be either Gitea's permissive values
    (converging the forge onto exactly what #1633 is about) or an opinion invented
    in Python, which is an SSOT whose real source is a code literal.

    ASSERTED ON TEXT ONLY THIS BRANCH PRODUCES, because the first version of this
    test was not. It asserted `"repository_settings" in str(exc.value)` — and the
    MISSING-FIELDS branch says "`repository_settings` is missing [...]" too, so a
    `load_settings` that quietly turned an absent block into `{}` still raised, still
    mentioned the key, and still passed. Caught by mutation, not by reading: the
    mutant defaulted the block and all 88 tests stayed green.

    That is this module's recurring defect one level up — a check confirming a
    weaker claim than it appears to. "It raised something naming the key" is not
    "it refused an absent block".
    """
    with pytest.raises(ValueError) as exc:
        load_settings({"apps": {"services": {"core": {"gitea": {}}}}})

    message = str(exc.value)
    assert "is absent" in message and "required rather than defaulted" in message
    assert "is missing" not in message, (
        "an absent block is reporting as a partial one, so this test would pass for a loader "
        "that defaulted the block to {} and then complained about its fields"
    )


def test_a_misspelled_setting_is_refused() -> None:
    """A typo is not a new setting.

    Dropped silently it leaves a field unmanaged; carried into the PATCH it makes
    the repository fail to converge on every future run while Gitea answers 200.
    """
    block = {**DECLARED_SETTINGS.to_api_payload(), "allow_squahs_merge": True}
    with pytest.raises(ValueError) as exc:
        load_settings({"apps": {"services": {"core": {"gitea": {"repository_settings": block}}}}})

    assert "allow_squahs_merge" in str(exc.value)


def test_a_partial_settings_block_is_refused() -> None:
    """Every field is declared explicitly, for the same reason `private:` is.

    A field omitted here is a field whose value is whatever the forge happens to
    hold — which is the reproducibility hole the declaration exists to close, since
    a repository this reconciler ever re-creates would come back with Gitea's
    defaults and silently revert the choice.
    """
    block = DECLARED_SETTINGS.to_api_payload()
    del block["default_merge_style"]
    with pytest.raises(ValueError) as exc:
        load_settings({"apps": {"services": {"core": {"gitea": {"repository_settings": block}}}}})

    assert "default_merge_style" in str(exc.value)


def test_the_declaration_carries_the_gate_on_the_merge_fields() -> None:
    """`has_pull_requests` is not a unit toggle here — it is what makes the rest apply.

    MEASURED AGAINST PROD 2026-09-04, the same PATCH body twice against
    `teledyne/openkm-brain`:

        without has_pull_requests   200 -> 0/6 merge fields applied
        with    has_pull_requests   200 -> 6/6 merge fields applied

    Gitea applies the merge settings inside the block that updates the
    pull-requests unit, so a payload that does not declare the unit enabled skips
    every one of them and still answers 200.

    Guarded HERE as well as by the run-time read-back, because the two catch it at
    different costs: `ensure_settings` turns its removal into a failed reconcile
    against the live forge, while this turns it into a failed test. Nothing about
    the name says "load-bearing", so the field is exactly the kind a later tidy-up
    removes as unrelated to merge behaviour.
    """
    payload = DECLARED_SETTINGS.to_api_payload()

    assert payload.get("has_pull_requests") is True, (
        "the merge fields below are silently inert without this; measured 0/6 applied"
    )
    merge_fields = {
        "default_merge_style",
        "allow_merge_commits",
        "allow_squash_merge",
        "allow_rebase",
        "allow_rebase_explicit",
        "allow_fast_forward_only_merge",
        "default_delete_branch_after_merge",
    }
    assert merge_fields <= set(payload), (
        "the gate is declared but the fields it gates are not; nothing is being set"
    )
