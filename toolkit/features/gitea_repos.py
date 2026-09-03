"""Declarative organizations and repositories in Gitea (TOOL-035, #1076).

Before this, "migrate a repo" meant a manual `git push` to a remote created by
hand in the web UI -- untracked, unrepeatable, invisible to review. ADR-065 then
decided *where inside the forge* repositories live and *which* ones move, leaving
only the mechanism unbuilt. This is the mechanism.

TWO HALVES, AND THE SPLIT IS LOAD-BEARING. `plan_reconcile` is pure: two sets in,
a plan out, no network. `execute` takes a plan and talks to Gitea. Everything
worth asserting about safety is a property of the plan, so it can be asserted
structurally instead of by hoping a code path is never reached -- see
`test_the_plan_has_no_deletion_field`.

DELETION IS NOT EXPRESSIBLE, not merely not performed. #1076 scopes this to
create-and-report: an undeclared repository is reported, never removed. So
`ReconcilePlan` has no field a deletion could travel in. Adding one is a
deliberate act that fails a test, rather than a refactor nobody notices.

WHO CREATES WHAT, and why it is not an implementation detail. Measured against
the live instance on 2026-08-27 with a throwaway organization:

    bot   POST /orgs   -> 403  required=[write:organization], token scope=write:repo...
    admin POST /orgs   -> 201  teams: [('Owners','owner')]  members: ['manu']

The account that creates an organization becomes the sole member of its `Owners`
team. ADR-065 D1 requires the machine identity to own NOTHING, so that retiring it
is a membership deletion rather than a data migration -- which means organizations
must be created by the superadmin, full stop. The bot creates repositories INSIDE
organizations, which confers no ownership of them.

That also dissolves the contradiction ADR-065 appeared to carry: D1 says the bot
owns nothing while its Consequences say the bot's token must widen to
`write:organization`. Both hold, because scope and ownership are different layers
-- `write:organization` is permission to ACT ON organizations, not to own them.

A CAUTION CARRIED FROM THE SAME MEASUREMENT. Creating a team with an explicit
`units` list and `permission: "write"` came back as `permission: none`. Passing
`units` appears to override the coarse field rather than combine with it, so
`ensure_team` reads the team back and asserts its effective permission. Trusting
the request body would ship a team that grants nothing, with nothing looking
wrong -- the silent shape this repo keeps writing lessons about.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Mapping

if TYPE_CHECKING:
    from toolkit.features.gitea_client import GiteaClient


class Actor(enum.Enum):
    """Which credential performs an operation.

    Not a preference: ADR-065 D1 turns this into an acceptance criterion, because
    the creating account becomes the owner.
    """

    SUPERADMIN = "superadmin"
    MACHINE = "machine"


@dataclass(frozen=True)
class DeclaredRepo:
    """One repository, as declared in the SSOT.

    `private` defaults to True and there is deliberately no way to reach a public
    repository by omission. `gitea.kubelab.live` has a public Cloudflare A record;
    `REQUIRE_SIGNIN_VIEW` closes the anonymous surface (SEC-GITEA-001), but
    confidentiality should not rest on a single setting staying true.
    """

    org: str
    name: str
    private: bool = True


@dataclass(frozen=True)
class ReconcilePlan:
    """What reconciliation would do. Creates and reports -- never deletions.

    The absence of a deletion field is the safety property, asserted structurally
    by the test suite. Do not add one without reading #1076's scope section.
    """

    orgs_to_create: tuple[str, ...] = ()
    repos_to_create: tuple[DeclaredRepo, ...] = ()
    undeclared_orgs: tuple[str, ...] = ()
    undeclared_repos: tuple[str, ...] = ()

    @property
    def is_noop(self) -> bool:
        """True when a second run would change nothing -- AC1's idempotence.

        Strays do not count: reporting one is not a change to the forge, and a
        forge holding an undeclared repository is still converged with respect to
        what was declared.
        """
        return not self.orgs_to_create and not self.repos_to_create


def actor_for_org_creation() -> Actor:
    """Organizations are created by the superadmin. See the module docstring."""
    return Actor.SUPERADMIN


def actor_for_repo_creation() -> Actor:
    """Repositories inside an organization are created by the machine identity."""
    return Actor.MACHINE


def plan_reconcile(
    declared: Mapping[str, Iterable[str]],
    existing_orgs: set[str],
    existing_repos: set[str],
) -> ReconcilePlan:
    """Compare the declaration against the forge. Pure -- no network, no side effects.

    `declared` maps organization -> repository names. An organization declared with
    an empty list is still created: ADR-065 D3 declares `kubelab` while it holds
    nothing, because an organization that exists only because someone made it in
    the UI is state with no consumer.

    `existing_repos` is a set of `"org/name"` strings, the same shape the API
    listing is normalised into.
    """
    declared_orgs = set(declared)
    declared_repos = {f"{org}/{name}" for org, names in declared.items() for name in names}

    orgs_to_create = tuple(sorted(declared_orgs - existing_orgs))

    repos_to_create = tuple(
        DeclaredRepo(org=org, name=name)
        for org, name in sorted(
            (org, name) for org, names in declared.items() for name in names if f"{org}/{name}" not in existing_repos
        )
    )

    # Reported, never acted on. The corollary ADR-065 D3 binds the reconciler to:
    # "import by accident must not become policy by inertia."
    undeclared_orgs = tuple(sorted(existing_orgs - declared_orgs))
    undeclared_repos = tuple(sorted(existing_repos - declared_repos))

    return ReconcilePlan(
        orgs_to_create=orgs_to_create,
        repos_to_create=repos_to_create,
        undeclared_orgs=undeclared_orgs,
        undeclared_repos=undeclared_repos,
    )


def load_declaration(common: Mapping[str, Any]) -> dict[str, list[str]]:
    """Read `gitea.organizations` out of a parsed common.yaml.

    `Any` rather than `object` in the value position: this walks an arbitrarily
    nested YAML document by chained `.get`, which `object` cannot express. The
    return type is where the precision belongs, and it is exact.

    Returns organization -> repository names. Absent declaration is an empty dict
    rather than an error: a forge with nothing declared is a valid state, and it
    is the state this repository was in until TOOL-035.
    """
    orgs = (common.get("apps", {}).get("services", {}).get("core", {}).get("gitea", {}).get("organizations", {})) or {}
    return {name: list((spec or {}).get("repositories", []) or []) for name, spec in orgs.items()}


def format_plan(plan: ReconcilePlan) -> str:
    """Human-readable plan, including the strays.

    Strays are printed even when there is nothing to create, because "no change"
    and "no change, and by the way three repositories here were never declared"
    are different operational facts and only one of them needs a decision.
    """
    lines: list[str] = []
    for org in plan.orgs_to_create:
        lines.append(f"  + org  {org}")
    for repo in plan.repos_to_create:
        lines.append(f"  + repo {repo.org}/{repo.name}" + ("" if repo.private else "  (PUBLIC)"))
    # Distinct names from the loops above, and not only for style: the created
    # entries are `DeclaredRepo`s while the strays are `"org/name"` strings, so
    # reusing `repo` shadows one type with the other and mypy refuses it.
    for stray_org in plan.undeclared_orgs:
        lines.append(f"  ? org  {stray_org}   undeclared — reported, not removed")
    for stray_repo in plan.undeclared_repos:
        lines.append(f"  ? repo {stray_repo}   undeclared — reported, not removed")
    if not lines:
        return "  (nothing to do — forge matches the declaration)"
    return "\n".join(lines)


def split_full_name(full_name: str) -> tuple[str, str]:
    """Split `owner/name`, refusing anything else with a message worth reading.

    SHARED BY THE CALLER AND THE PLANNER ON PURPOSE. When the CLI did its own
    `full_name.split("/", 1)` before consulting `plan_drop`, a malformed target
    died on `ValueError: not enough values to unpack (expected 2, got 1)` --
    accurate, and it names Python's problem rather than the operator's. The
    planner's careful refusal was unreachable because the split ran first.

    Refusing here also keeps a typo from ever becoming a URL: `DELETE /repos/resume`
    is a well-formed request to the wrong thing.
    """
    owner, _, name = full_name.partition("/")
    if not owner or not name or "/" in name:
        raise ValueError(
            f"{full_name!r} is not an `owner/name` repository reference. Refused before building a "
            f"URL from it: `DELETE /repos/{full_name}` would address something nobody meant."
        )
    return owner, name


@dataclass(frozen=True)
class DropDecision:
    """Whether one repository may be dropped, and why not when it may not.

    A VERDICT, NEVER AN ACTOR. It holds no client and no callable, asserted
    structurally by `test_the_decision_carries_no_capability` -- the same reasoning
    that keeps `ReconcilePlan` free of a deletion field. Planning stays unable to
    perform the thing it plans.
    """

    may_drop: bool
    reason: str | None = None


def plan_drop(full_name: str, repo: Mapping[str, Any] | None, declared: set[str]) -> DropDecision:
    """Decide whether an EMPTY DECLARED repository may be removed. Pure -- no network.

    WHY THIS DOES NOT REOPEN #1076'S DELETION QUESTION. The reconciler still cannot
    delete: `ReconcilePlan` has no field for it and `execute` has no path to it.
    This is a separate operator-triggered command with its own object, and it
    exists for one situation -- PR1 created the declared repositories as empty
    shells, and `POST /repos/migrate` answers 409 rather than filling one, so the
    shells block the migration they were declared for.

    THREE REFUSALS, and the order is deliberate -- each answers a different
    question, and the first two would be wrong to skip even if the third held:

    - **Malformed target.** `owner/name` or nothing. A typo must not become a URL.
    - **Not declared.** A stray survives, always. Emptiness does not make someone
      else's repository ours to remove (ADR-065 D3), and a stray is precisely the
      object whose removal needs a human who knows what it was.
    - **Not empty, or emptiness unknown.** `empty` is the field Gitea maintains for
      this; `size` is not a proxy for it. A freshly created empty repository
      reports `size: 22` -- the git directory itself -- measured on all three
      shells 2026-09-02. An absent `empty` key is "I do not know", refused rather
      than defaulted, because defaulting it to True deletes on a missing value.

    None of these guards the CREDENTIAL, which is the point worth remembering: the
    superadmin's basic-auth session can delete any repository on the instance, and
    it does not consult this function. These refusals catch operator error. The
    safety property that does not depend on anyone's care is that no TOKEN was
    widened to make this work -- see the module docstring of the test file.
    """
    split_full_name(full_name)

    if repo is None:
        return DropDecision(False, f"{full_name} is already absent — nothing to drop")

    if full_name not in declared:
        return DropDecision(
            False,
            f"{full_name} is not declared in `apps.services.core.gitea.organizations`. Undeclared "
            f"repositories are reported and never removed (#1076, ADR-065 D3) — being empty does "
            f"not change that. Declare it first if it really is ours.",
        )

    if "empty" not in repo:
        return DropDecision(
            False,
            f"Gitea did not report whether {full_name} is empty. That is 'I do not know', not 'it "
            f"is empty' — refusing rather than deleting on a missing field.",
        )

    if not repo["empty"]:
        return DropDecision(
            False,
            f"{full_name} is not empty (size={repo.get('size', '?')}). This command removes the "
            f"shells PR1 created, never a repository with content.",
        )

    return DropDecision(True)


# =============================================================================
# The I/O half. Everything above is pure; everything below talks to Gitea.
# =============================================================================

#: The team the bot is added to in every declared organization. It exists because
#: ADR-065 D1 keeps the bot out of `Owners`: without a write team the bot is a
#: non-member and cannot create repositories in an organization it does not own.
TEAM_NAME = "reconcilers"
TEAM_PERMISSION = "write"


class TeamPermissionError(Exception):
    """A team exists but does not grant what it was asked to grant.

    Its own category rather than a generic error because the failure is silent by
    nature: the request succeeds, the team appears, and every later repository
    creation is refused for a reason that points somewhere else.
    """


@dataclass
class ExecutionReport:
    """What `execute` actually did, as opposed to what the plan proposed.

    Separate from `ReconcilePlan` on purpose. The plan is a prediction and the
    report is an observation, and collapsing the two is how "we planned to create
    three organizations" becomes indistinguishable from "we created three".
    """

    orgs_created: list[str] = field(default_factory=list)
    repos_created: list[str] = field(default_factory=list)
    teams_ensured: list[str] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def ensure_team(admin: GiteaClient, org: str, member: str | None = None) -> dict[str, Any]:
    """Ensure `org` has the write team, and that it genuinely grants write.

    READS THE TEAM BACK RATHER THAN TRUSTING THE RESPONSE, and this is still the
    whole point of the function. What changed on 2026-09-02 is WHICH FIELD it
    reads back, because the original one answered a different question than the
    one being asked.

    The old check asserted `team["permission"] == "write"` and raised on `none`.
    That reading was wrong: `permission` is the team's COARSE access mode, and
    Gitea sets it to `none` exactly when the grant moves per-unit via `units_map`
    -- which is the only shape Gitea 1.25 accepts. So the check refused correct
    teams, and would have gone on refusing them however the payload was rewritten.

    Settled by consequence rather than by field: a team with `units_map` set and
    `can_create_org_repo: true` reads back `permission: none` AND lets the bot
    create a repository (201, measured). A team with `units_map` alone reads back
    identically and is refused with `Given user is not allowed to create
    repository in organization`. The coarse field cannot tell those two apart;
    `can_create_org_repo` is the field that decides, so that is what is asserted.

    Still a field check, not a live one: asserting by consequence here would mean
    creating a probe repository on every reconcile. The fields checked are now
    the ones that actually govern, which is the property the old check lacked.
    """
    team = admin.get_team(org, TEAM_NAME)
    if team is None:
        admin.create_team(org, TEAM_NAME, TEAM_PERMISSION)
        # Deliberately re-fetched rather than using the create response: the
        # create response is exactly the artefact measured to be unreliable.
        team = admin.get_team(org, TEAM_NAME)

    if team is None:
        raise TeamPermissionError(f"team {org}/{TEAM_NAME} was created but does not read back")

    if not team.get("can_create_org_repo"):
        raise TeamPermissionError(
            f"team {org}/{TEAM_NAME} has can_create_org_repo unset. Repository creation inside an "
            "organization is governed by that boolean, NOT by the repo.code unit: measured 2026-09-02, "
            "a team with units_map at write and the flag unset refused the bot with 'Given user is not "
            "allowed to create repository in organization'. Note the coarse `permission` field reads "
            f"{team.get('permission')!r} on a correct team too, so it cannot be used to tell them apart."
        )

    units = team.get("units_map") or {}
    if units.get("repo.code") != TEAM_PERMISSION:
        raise TeamPermissionError(
            f"team {org}/{TEAM_NAME} grants repo.code {units.get('repo.code')!r}, expected "
            f"{TEAM_PERMISSION!r}. The team can create repositories but could not push to them, and "
            "the resulting refusal is the same 403 as a missing token scope -- the trap AUTH-004 AC5 "
            "already recorded once."
        )

    if member:
        admin.add_team_member(int(team["id"]), member)
    return team


def _handle_failure(report: ExecutionReport, target: str, exc: Exception) -> None:
    """Record a failed operation and let the run continue.

    COLLECT, DO NOT ABORT, and the reason is that aborting buys nothing here.
    Three things make continuing strictly better:

    - **The cascade is already quarantined.** `execute` tracks `failed_orgs` and
      skips the repositories inside them, so continuing cannot attempt work whose
      precondition is missing. Aborting would only stop work that was going to
      succeed.
    - **A re-run is free.** The reconciler is idempotent by construction, so a
      partially applied run is recovered by running it again -- there is no
      half-state to clean up first.
    - **The first run is the one that fails, and it fails by class.** A token
      minted without `write:organization` refuses every organization, and a run
      that stops at the first refusal reports one failure where there are five.
      Seeing them together is what tells "this credential is wrong" apart from
      "this one organization is odd".

    `str(exc)` rather than the exception: `GiteaError` carries Gitea's own
    diagnostics in its message, including the `required=[...] token scope=[...]`
    text that told a scope problem apart from a permission problem in Risk 1.
    """
    report.failures.append((target, str(exc)))


def execute(
    plan: ReconcilePlan,
    admin: GiteaClient,
    bot: GiteaClient,
    bot_username: str,
) -> ExecutionReport:
    """Carry out a plan, with each operation performed by the credential that may.

    TWO CLIENTS, NOT ONE, and the split is the acceptance criterion rather than a
    style choice: `admin` creates organizations because Gitea puts the creator in
    `Owners` and ADR-065 D1 requires the bot to own nothing; `bot` creates
    repositories inside them, which confers no ownership. `actor_for_org_creation`
    and `actor_for_repo_creation` encode the same answer for the test suite.

    Nothing here deletes. `plan.undeclared_*` is carried into the report by the
    caller's formatting, never into a call.
    """
    report = ExecutionReport()
    failed_orgs: set[str] = set()

    for org in plan.orgs_to_create:
        try:
            admin.create_org(org)
            report.orgs_created.append(org)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, whatever its type
            failed_orgs.add(org)
            _handle_failure(report, f"org {org}", exc)

    # Every organization that will receive a repository needs the bot in a write
    # team -- including organizations that already existed, which is why this
    # iterates the repositories' orgs rather than `orgs_created`.
    for org in sorted({repo.org for repo in plan.repos_to_create} - failed_orgs):
        try:
            ensure_team(admin, org, member=bot_username)
            report.teams_ensured.append(org)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, whatever its type
            failed_orgs.add(org)
            _handle_failure(report, f"team {org}/{TEAM_NAME}", exc)

    for repo in plan.repos_to_create:
        if repo.org in failed_orgs:
            # Not a failure of its own: a repository whose organization could not
            # be prepared was never attempted, and reporting it as failed would
            # inflate one root cause into many.
            continue
        try:
            bot.create_repo(repo.org, repo.name, private=repo.private)
            report.repos_created.append(f"{repo.org}/{repo.name}")
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, whatever its type
            _handle_failure(report, f"repo {repo.org}/{repo.name}", exc)

    return report
