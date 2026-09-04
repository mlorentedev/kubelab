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
class RepoSpec:
    """One repository as the DECLARATION writes it, before an organization is attached.

    Separate from `DeclaredRepo` so the org appears exactly once -- as the key of
    the mapping that holds these -- rather than in both the key and the record,
    where the two could disagree.

    `migrate_from` is `"<service>:<owner>/<name>"`, e.g. `github:mlorentedev/resume`.
    Optional, and its absence means something specific: a repository that starts
    life in Gitea has nowhere to come from, so requiring the field would force a
    fictional source on the next new repository.
    """

    name: str
    migrate_from: str | None = None
    private: bool = True


@dataclass(frozen=True)
class DeclaredRepo:
    """One repository, as declared in the SSOT, with its organization resolved.

    `private` defaults to True and there is deliberately no way to reach a public
    repository by omission. `gitea.kubelab.live` has a public Cloudflare A record;
    `REQUIRE_SIGNIN_VIEW` closes the anonymous surface (SEC-GITEA-001), but
    confidentiality should not rest on a single setting staying true.
    """

    org: str
    name: str
    private: bool = True
    migrate_from: str | None = None


@dataclass(frozen=True)
class ReconcilePlan:
    """What reconciliation would do. Creates and reports -- never deletions.

    The absence of a deletion field is the safety property, asserted structurally
    by the test suite. Do not add one without reading #1076's scope section.
    """

    orgs_to_create: tuple[str, ...] = ()
    repos_to_create: tuple[DeclaredRepo, ...] = ()
    repos_to_migrate: tuple[DeclaredRepo, ...] = ()
    undeclared_orgs: tuple[str, ...] = ()
    undeclared_repos: tuple[str, ...] = ()

    @property
    def is_noop(self) -> bool:
        """True when a second run would change nothing -- AC1's idempotence.

        Strays do not count: reporting one is not a change to the forge, and a
        forge holding an undeclared repository is still converged with respect to
        what was declared.
        """
        return not self.orgs_to_create and not self.repos_to_create and not self.repos_to_migrate


def actor_for_org_creation() -> Actor:
    """Organizations are created by the superadmin. See the module docstring."""
    return Actor.SUPERADMIN


def actor_for_repo_creation() -> Actor:
    """Repositories inside an organization are created by the machine identity."""
    return Actor.MACHINE


def plan_reconcile(
    declared: Mapping[str, Iterable[RepoSpec]],
    existing_orgs: set[str],
    existing_repos: set[str],
) -> ReconcilePlan:
    """Compare the declaration against the forge. Pure -- no network, no side effects.

    `declared` maps organization -> repository specs. An organization declared with
    an empty list is still created: ADR-065 D3 declares `kubelab` while it holds
    nothing, because an organization that exists only because someone made it in
    the UI is state with no consumer.

    `existing_repos` is a set of `"org/name"` strings, the same shape the API
    listing is normalised into.

    MISSING-AND-HAS-A-SOURCE MEANS MIGRATE, NOT CREATE, and that split is the whole
    reason `RepoSpec` carries `migrate_from`. Before it, a declared-and-absent
    repository could only be created EMPTY -- and Gitea's `POST /repos/migrate`
    answers 409 when the target already exists, so every shell the reconciler made
    permanently blocked the move it was declared for. Measured on all three
    declared repositories, 2026-09-02: `empty=True, size=22`.

    PRESENCE IS PRESENCE, whatever put it there. A repository that already arrived
    appears in neither list, so a second run is a no-op on both paths. That matters
    more on the migrate path than the create path: re-creating is harmlessly
    refused, while a reconciler that kept proposing a migration for a repository
    that had already migrated would report a permanent failure on a converged forge.
    """
    declared_orgs = set(declared)
    declared_repos = {f"{org}/{spec.name}" for org, specs in declared.items() for spec in specs}

    orgs_to_create = tuple(sorted(declared_orgs - existing_orgs))

    # Sorted by `(org, name)` explicitly, not by the tuple: `RepoSpec` is a frozen
    # dataclass without ordering, so a bare `sorted()` compares specs whenever two
    # share an organization and raises. The output order is part of what makes the
    # printed plan reviewable, so it is stated rather than incidental.
    missing = sorted(
        (
            (org, spec)
            for org, specs in declared.items()
            for spec in specs
            if f"{org}/{spec.name}" not in existing_repos
        ),
        key=lambda pair: (pair[0], pair[1].name),
    )

    repos_to_create = tuple(
        DeclaredRepo(org=org, name=spec.name, private=spec.private) for org, spec in missing if not spec.migrate_from
    )

    repos_to_migrate = tuple(
        DeclaredRepo(org=org, name=spec.name, private=spec.private, migrate_from=spec.migrate_from)
        for org, spec in missing
        if spec.migrate_from
    )

    # Reported, never acted on. The corollary ADR-065 D3 binds the reconciler to:
    # "import by accident must not become policy by inertia."
    undeclared_orgs = tuple(sorted(existing_orgs - declared_orgs))
    undeclared_repos = tuple(sorted(existing_repos - declared_repos))

    return ReconcilePlan(
        orgs_to_create=orgs_to_create,
        repos_to_create=repos_to_create,
        repos_to_migrate=repos_to_migrate,
        undeclared_orgs=undeclared_orgs,
        undeclared_repos=undeclared_repos,
    )


def load_declaration(common: Mapping[str, Any]) -> dict[str, list[RepoSpec]]:
    """Read `gitea.organizations` out of a parsed common.yaml.

    `Any` rather than `object` in the value position: this walks an arbitrarily
    nested YAML document by chained `.get`, which `object` cannot express. The
    return type is where the precision belongs, and it is exact.

    Returns organization -> repository specs. Absent declaration is an empty dict
    rather than an error: a forge with nothing declared is a valid state, and it
    is the state this repository was in until TOOL-035.

    EACH ENTRY IS A MAPPING, never a bare name. The bare-name form is what let a
    declaration say *that* a repository should exist without saying *where it comes
    from*, and the only thing the reconciler could then do was create an empty
    shell. Accepting both shapes would keep that hole open for whoever writes the
    next entry, so the loader refuses a string outright rather than defaulting its
    source to None.
    """
    orgs = (common.get("apps", {}).get("services", {}).get("core", {}).get("gitea", {}).get("organizations", {})) or {}

    declaration: dict[str, list[RepoSpec]] = {}
    for org, spec in orgs.items():
        entries = (spec or {}).get("repositories", []) or []
        specs: list[RepoSpec] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError(
                    f"`{org}.repositories` contains {entry!r}, a bare name. Each entry must be a "
                    f"mapping with at least `name:`, and `migrate_from:` when the repository is a "
                    f"move rather than new work — a declaration that cannot say where a repository "
                    f"comes from can only create it empty, and Gitea then refuses to migrate into "
                    f"it with 409."
                )
            specs.append(
                RepoSpec(
                    name=str(entry["name"]),
                    migrate_from=entry.get("migrate_from"),
                    private=bool(entry.get("private", True)),
                )
            )
        declaration[org] = specs
    return declaration


def declared_full_names(declaration: Mapping[str, Iterable[RepoSpec]]) -> set[str]:
    """Every declared repository as `"org/name"` -- the shape the API listing normalises into.

    A FUNCTION RATHER THAN A COMPREHENSION AT EACH CALL SITE, because there were two
    and they drifted the moment the declaration's shape changed. `drop-empty` built
    its own `{f"{org}/{name}" for org, names in load_declaration(...)}`, which after
    `RepoSpec` landed produced strings like `"personal/RepoSpec(name='resume', ...)"`
    -- so a declared repository read as undeclared and the command refused to touch
    it. Measured 2026-09-02 against prod.

    It failed SAFE, which is the only reason it cost minutes rather than data: the
    membership test guards a deletion, so garbage on one side means refuse. A shape
    change is not obliged to be that kind, and the fix is to have one producer of
    this set rather than to have been lucky.
    """
    return {f"{org}/{spec.name}" for org, specs in declaration.items() for spec in specs}


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
    for repo in plan.repos_to_migrate:
        # The source is printed because a migration is the one operation here whose
        # blast radius reaches outside the forge: it reads a remote repository with
        # a credential, and an operator approving `--apply` should see WHICH remote
        # without going to look it up.
        lines.append(
            f"  ~ repo {repo.org}/{repo.name}   migrate from {repo.migrate_from}"
            + ("" if repo.private else "  (PUBLIC)")
        )
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


#: Forges `migrate_from` can name, mapped to the `service` value Gitea's migration
#: endpoint expects. A closed set rather than a passthrough: `service` decides
#: whether Gitea uses the provider's API (which is what carries issues and pull
#: requests) or falls back to a plain git clone, and an unrecognised value fails
#: over to `git` SILENTLY -- the code would arrive, the issues would not, and the
#: run would report success. AC3 is precisely the claim that would be false.
MIGRATION_SERVICES: dict[str, str] = {"github": "github", "gitlab": "gitlab", "gitea": "gitea"}


def parse_migration_source(migrate_from: str) -> tuple[str, str]:
    """Turn `"<service>:<owner>/<name>"` into `(service, clone_addr)`.

    `github:mlorentedev/resume` -> `("github", "https://github.com/mlorentedev/resume.git")`.

    THE SERVICE IS VALIDATED AGAINST A CLOSED SET, and that is the part worth
    keeping. Gitea treats an unknown `service` as a plain git migration, which
    succeeds -- it clones the code -- while silently dropping issues, pull
    requests, labels, milestones and releases. A typo in the declaration would
    therefore produce a green run and a repository missing everything AC3 is about,
    which is the fails-open shape this spec keeps finding.

    The credential is NOT part of the address. It travels in the request body as
    `auth_token`, never embedded in `clone_addr`, so it cannot end up in Gitea's
    stored remote URL or in an error message that echoes the address back.
    """
    service, _, path = migrate_from.partition(":")
    if service not in MIGRATION_SERVICES:
        raise ValueError(
            f"unknown migration service {service!r} in {migrate_from!r}. Known: "
            f"{sorted(MIGRATION_SERVICES)}. Gitea treats an unrecognised service as a plain git "
            f"clone, which carries the code and silently drops issues and pull requests — so this "
            f"is refused here rather than discovered as a repository that looks migrated."
        )

    owner, _, name = path.partition("/")
    if not owner or not name or "/" in name:
        raise ValueError(f"{migrate_from!r} must be `<service>:<owner>/<name>` — got path {path!r}.")

    return MIGRATION_SERVICES[service], f"https://{service}.com/{owner}/{name}.git"


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
    repos_migrated: list[str] = field(default_factory=list)
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

    # CONVERGE A TEAM THAT PREDATES THE CURRENT GRANT, then re-read. `ensure_team`
    # only ever created, so a team born before `includes_all_repositories` was set
    # kept covering zero repositories forever and no amount of re-running fixed it.
    # Both live teams were in exactly that state. Raising instead would have been
    # honest and useless: it would fail every reconcile until someone edited the
    # forge by hand, which is the manual step this whole feature replaces.
    if not team.get("includes_all_repositories"):
        admin.edit_team(int(team["id"]), TEAM_NAME, TEAM_PERMISSION)
        team = admin.get_team(org, TEAM_NAME)
        if team is None:
            raise TeamPermissionError(f"team {org}/{TEAM_NAME} does not read back after being widened")

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

    # THE SCOPE, WHICH EVERY CHECK ABOVE TAKES FOR GRANTED. A permission is a pair
    # -- what may be done, and to what -- and the three assertions above only ever
    # examined the first half. Measured on prod 2026-09-03: both teams passed all
    # of them while covering zero repositories, so the bot could read the migrated
    # repositories and push to none of them.
    #
    # This is lesson-416 on a grant: an empty scope is not a weak permission, it is
    # a permission over nothing, and it reads identically to a correct one in every
    # field-level check. Asserted last because it is the value the others depend on.
    if not team.get("includes_all_repositories"):
        raise TeamPermissionError(
            f"team {org}/{TEAM_NAME} has includes_all_repositories unset, so its units apply to no "
            "repository. Every other field on it can be correct and the bot still cannot push: "
            "measured 2026-09-03, `repo.code -> write` and `can_create_org_repo -> True` alongside "
            "`repos attached: NONE`, with push available only on the one repository the bot had "
            "created itself. A grant is what may be done AND to what; this is the second half."
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
    migration_token: str | None = None,
    migrator: GiteaClient | None = None,
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
    # iterates the repositories' orgs rather than `orgs_created`. Migrations count:
    # a migration creates a repository inside an organization exactly as a create
    # does, and omitting them here would refuse every migration into an
    # organization that receives nothing else.
    receiving = {repo.org for repo in plan.repos_to_create} | {repo.org for repo in plan.repos_to_migrate}
    for org in sorted(receiving - failed_orgs):
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

    for repo in plan.repos_to_migrate:
        if repo.org in failed_orgs:
            continue
        if migrator is None:
            _handle_failure(
                report,
                f"repo {repo.org}/{repo.name}",
                RuntimeError(
                    "no migrator client was supplied. Migration is the ONE operation here that no "
                    "token may perform -- measured 2026-09-02 against prod, asking each credential "
                    "to migrate an already-existing repository (409 means 'may', 403 means 'may "
                    "not'): bot token 403 'Given user is not owner of organization', admin token "
                    "403 required=[write:repository], superadmin basic auth 409. So the caller must "
                    "pass a GiteaBasicAuthClient."
                ),
            )
            continue
        if not migration_token:
            # Reported per repository rather than raised once, for the same reason
            # `_handle_failure` collects: the run should say which repositories did
            # not arrive, not stop at the first and leave the rest unaccounted for.
            _handle_failure(
                report,
                f"repo {repo.org}/{repo.name}",
                RuntimeError(
                    "no migration credential was supplied. The source is a private remote, so "
                    "`apps.services.core.gitea.github_migration_token` must be present in SOPS "
                    "for this environment."
                ),
            )
            continue
        try:
            service, clone_addr = parse_migration_source(str(repo.migrate_from))
            migrator.migrate_repo(
                repo.org,
                repo.name,
                clone_addr=clone_addr,
                service=service,
                auth_token=migration_token,
                private=repo.private,
            )
            # "Accepted", not "complete": Gitea keeps importing issues and pull
            # requests after the call returns. The CLI says so, because a report
            # that reads as done invites a verification count taken too early --
            # measured on `resume`, 98 pull requests then 147 minutes later.
            report.repos_migrated.append(f"{repo.org}/{repo.name}")
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, whatever its type
            _handle_failure(report, f"repo {repo.org}/{repo.name}", exc)

    return report
