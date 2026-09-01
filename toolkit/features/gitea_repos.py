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

    READS THE TEAM BACK RATHER THAN TRUSTING THE RESPONSE, and this is the whole
    point of the function. Measured 2026-08-27: a team created with an explicit
    `units` list and `permission: "write"` came back reporting `permission: none`.
    A reconciler that trusted the request body would ship a team granting nothing,
    and the resulting 403 on repository creation is the same status code as a
    missing token scope -- the trap AUTH-004 AC5 already recorded once.

    So a wrong permission raises here, where the cause is still visible, instead
    of surfacing later as an unexplained refusal.
    """
    team = admin.get_team(org, TEAM_NAME)
    if team is None:
        admin.create_team(org, TEAM_NAME, TEAM_PERMISSION)
        # Deliberately re-fetched rather than using the create response: the
        # create response is exactly the artefact measured to be unreliable.
        team = admin.get_team(org, TEAM_NAME)

    if team is None:
        raise TeamPermissionError(f"team {org}/{TEAM_NAME} was created but does not read back")

    effective = team.get("permission")
    if effective != TEAM_PERMISSION:
        raise TeamPermissionError(
            f"team {org}/{TEAM_NAME} reports permission {effective!r}, expected {TEAM_PERMISSION!r}. "
            "Gitea returns 'none' when `units` overrides the coarse permission field; a repository "
            "creation against this team would be refused with a 403 that looks like a token scope problem."
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
