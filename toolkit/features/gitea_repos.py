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
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from toolkit.features.gitea_client import TEAM_UNITS

if TYPE_CHECKING:
    from toolkit.features.gitea_client import GiteaBasicAuthClient, GiteaClient


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

    THAT DEFAULT STANDS, AND THE OPERATOR HAS OVERRIDDEN IT EXPLICITLY. Every
    declared repository carries `private: false` as of 2026-09-03, accepting the
    single-control posture above with the trade-off measured rather than assumed:
    `REQUIRE_SIGNIN_VIEW` makes "public" mean *readable by any authenticated
    account*, local registration and OpenID signup are both closed, and the only
    door is Authelia, which has no self-registration. The readership is therefore
    `apps.auth.identities` and nobody else. The paragraph above is why omission
    still cannot reach public; this one is why declaring it is not a contradiction.
    """

    org: str
    name: str
    private: bool = True
    migrate_from: str | None = None


@dataclass(frozen=True)
class RepoSettings:
    """The repository settings the declaration insists on, for every declared repo.

    WHY THESE EXIST AT ALL. `POST /repos/migrate` carries code, issues, pull
    requests, labels, milestones and releases. It does NOT carry repository
    settings, and Gitea's defaults are permissive -- so a migrated repository does
    not arrive UNCONFIGURED, it arrives CONFIGURED DIFFERENTLY and more weakly than
    the one it replaced. Those are not the same problem: the first shows up as an
    empty field, the second reads as a working repository. Measured on all three,
    2026-09-04: `default_merge_style: merge` against a GitHub original that was
    squash-only, and every merge style allowed.

    FIELD NAMES ARE GITEA'S OWN `EditRepoOption` NAMES, deliberately, so the YAML
    key, this attribute and the PATCH body are one vocabulary with no mapping layer
    between them to drift. `to_api_payload` is therefore `asdict`, and a test pins
    the names against the live `GET /repos/{o}/{r}` output rather than against this
    class -- a payload built from our own dataclass and compared to our own
    dataclass certifies our belief about Gitea instead of testing it (lesson-423).

    ONE BLOCK FOR ALL DECLARED REPOSITORIES, no per-repository override. All three
    want the same thing, and an override mechanism with no user is a second place
    for the answer to live. Branch protection is where per-repository declaration
    becomes unavoidable -- `fae-brain` and `openkm-brain` have no CI on this forge,
    so a shared required-checks list would block every pull request there forever --
    and that is the reason it is a separate slice of #1633 rather than laziness.

    `has_actions` IS ABSENT AND MUST STAY ABSENT: act_runner needs it, and a
    declaration that turned it off would take CI down on the repository that just
    got it (personal/resume#260).

    `has_pull_requests` IS PRESENT AND MUST STAY PRESENT, and it is not here because
    anyone wants to toggle it. It is the GATE on every other merge field. Measured
    against prod on 2026-09-04, the same PATCH body twice on `teledyne/openkm-brain`:

        without has_pull_requests   200 -> 0/6 merge fields applied
        with    has_pull_requests   200 -> 6/6 merge fields applied

    Gitea applies the merge settings inside the block that updates the
    pull-requests UNIT, so a payload that does not say the unit is enabled skips
    them entirely -- and answers 200 either way. This was not deduced from the
    source: the first `--apply` against prod reported all three repositories
    unconverged, with `has_wiki` and `has_projects` applied and every merge field
    untouched. The post-condition is the only reason that was a red run and not a
    green one over a forge that still merges with merge commits.
    """

    default_merge_style: str
    #: The gate. See the class docstring -- removing it silently disables the six
    #: fields below, and `ensure_settings` is what turns that silence into a failure.
    has_pull_requests: bool
    allow_merge_commits: bool
    allow_squash_merge: bool
    allow_rebase: bool
    allow_rebase_explicit: bool
    allow_fast_forward_only_merge: bool
    default_delete_branch_after_merge: bool
    has_wiki: bool
    has_projects: bool

    def to_api_payload(self) -> dict[str, Any]:
        """The PATCH body. Every declared field, because every one is a declaration."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


def settings_needs_convergence(live: Mapping[str, Any] | None, declared: RepoSettings) -> bool:
    """Does this repository fall short of what `edit_repo` would set?

    ONE PREDICATE, TWO CALLERS -- the same discipline as `team_needs_convergence`,
    and for the same measured reason. If the plan's decision to schedule a
    repository and the executor's decision to PATCH it were separate expressions,
    they could disagree; on 2026-09-03 they did, and a correct repair sat in
    `ensure_team` that nothing ever reached (lesson-424).

    EVERY DECLARED FIELD IS COMPARED, not the interesting one. A predicate covering
    a subset is the same defect one field over: the plan would report a match on a
    repository whose `default_delete_branch_after_merge` was wrong, and the run
    would exit at `is_noop` before touching it.

    An absent repository needs convergence too. A repository this run is about to
    create or migrate arrives with Gitea's permissive defaults, so `None` -- "not
    there yet" -- is correctly short of the declaration, and the caller acting on
    this does not need to know which of the two cases it is looking at.
    """
    return bool(settings_changes(live, declared))


@dataclass(frozen=True)
class SettingsChange:
    """One repository whose settings fall short, and exactly which fields do.

    CARRIES THE DIFF RATHER THAN JUST THE NAME, because the printed plan is what an
    operator approves `--apply` on, and `~ settings personal/resume` tells them
    nothing about what is about to change. `default_merge_style: merge -> squash`
    tells them everything. This module already treats plan readability as a
    property worth code (`plan_reconcile` sorts explicitly so a diff between two
    runs is a real change); this is the same commitment one step further.

    `absent` distinguishes a repository this run is about to create -- which has no
    live values to diff against and will simply receive all of them -- from one that
    exists and disagrees. Printing nine `None -> x` lines for a new repository would
    bury the one repository whose settings actually drifted.
    """

    org: str
    name: str
    changes: tuple[tuple[str, Any, Any], ...] = ()
    absent: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.org}/{self.name}"


def settings_changes(live: Mapping[str, Any] | None, declared: RepoSettings) -> tuple[tuple[str, Any, Any], ...]:
    """`(field, live_value, declared_value)` for every field that disagrees.

    THE SAME COMPARISON `settings_needs_convergence` MAKES, and deliberately its
    only implementation: that predicate is now `bool(settings_changes(...))`, so the
    question "does this need work" and the question "what work" cannot answer
    differently. Two expressions of one comparison is how a plan comes to report a
    field the executor does not send, or the reverse.
    """
    if live is None:
        return tuple((key, None, value) for key, value in declared.to_api_payload().items())
    return tuple(
        (key, live.get(key), value) for key, value in declared.to_api_payload().items() if live.get(key) != value
    )


@dataclass(frozen=True)
class VisibilityDrift:
    """A repository that exists, but not with the visibility that was declared.

    REPORTED, NEVER CORRECTED, for the same reason the plan has no deletion field:
    flipping a repository's visibility is a disclosure decision, and a reconciler
    that made it silently on the strength of a YAML edit would be a worse tool than
    one that says what it found. `execute` does not read this.
    """

    org: str
    name: str
    declared_private: bool
    live_private: bool

    @property
    def full_name(self) -> str:
        return f"{self.org}/{self.name}"


@dataclass(frozen=True)
class ReconcilePlan:
    """What reconciliation would do. Creates and reports -- never deletions.

    The absence of a deletion field is the safety property, asserted structurally
    by the test suite. Do not add one without reading #1076's scope section.
    """

    orgs_to_create: tuple[str, ...] = ()
    repos_to_create: tuple[DeclaredRepo, ...] = ()
    repos_to_migrate: tuple[DeclaredRepo, ...] = ()
    teams_to_converge: tuple[str, ...] = ()
    repos_to_configure: tuple[SettingsChange, ...] = ()
    undeclared_orgs: tuple[str, ...] = ()
    undeclared_repos: tuple[str, ...] = ()
    visibility_drift: tuple[VisibilityDrift, ...] = ()

    @property
    def is_noop(self) -> bool:
        """True when a second run would change nothing -- AC1's idempotence.

        THE RULE, STATED ONCE SO THE NEXT FIELD DOES NOT HAVE TO GUESS: anything
        `execute` acts on belongs here; anything reported and never acted on does
        not. That is what separates `teams_to_converge` from `visibility_drift`,
        which look alike -- both are a live value disagreeing with the declaration
        -- and are opposites. `execute` calls `ensure_team`; nothing anywhere reads
        `visibility_drift`, because flipping a repository's visibility is a
        disclosure decision this tool refuses to make.

        Strays do not count either: reporting one is not a change to the forge, and
        a forge holding an undeclared repository is still converged with respect to
        what was declared.

        `teams_to_converge` was added because omitting it made the property lie in
        the direction that hides work. The CLI returns early on `is_noop`, so a
        forge whose teams needed repair reported "nothing to create" and exited
        before `execute` ran -- measured on prod 2026-09-03, every declared
        repository already present and both teams covering none of them.
        `repos_to_configure` is the same kind of field and joins for the same
        reason: `execute` acts on it.
        """
        return (
            not self.orgs_to_create
            and not self.repos_to_create
            and not self.repos_to_migrate
            and not self.teams_to_converge
            and not self.repos_to_configure
        )


def actor_for_org_creation() -> Actor:
    """Organizations are created by the superadmin. See the module docstring."""
    return Actor.SUPERADMIN


def actor_for_repo_creation() -> Actor:
    """Repositories inside an organization are created by the machine identity."""
    return Actor.MACHINE


def plan_reconcile(
    declared: Mapping[str, Iterable[RepoSpec]],
    existing_orgs: set[str],
    existing_repos: Mapping[str, bool],
    existing_teams: Mapping[str, Mapping[str, Any] | None],
    existing_repo_settings: Mapping[str, Mapping[str, Any] | None],
    declared_settings: RepoSettings,
) -> ReconcilePlan:
    """Compare the declaration against the forge. Pure -- no network, no side effects.

    `declared` maps organization -> repository specs. An organization declared with
    an empty list is still created: ADR-065 D3 declares `kubelab` while it holds
    nothing, because an organization that exists only because someone made it in
    the UI is state with no consumer.

    `existing_repos` maps `"org/name"` to whether the forge holds it PRIVATE, which
    is the shape `GiteaClient.list_repos` returns.

    IT IS A MAPPING AND NOT A SET, AND THE PARAMETER IS REQUIRED, because the
    alternative was an optional visibility argument -- and an optional argument that
    silently skips a comparison is the precise defect this comparison exists to
    catch. Before this, the plan compared EXISTENCE only: a repository declared
    private and living public was reported as converged, and `make gitea-reconcile`
    ended with "forge matches the declaration". The declaration and the forge
    disagreed about who could read the code, and every check in the path passed.
    Measured 2026-09-03 on prod, where all three repositories read `private=False`
    against a declaration that then said nothing at all.

    Membership tests read identically on a mapping, so the existence logic below is
    unchanged; only set algebra needs `set(existing_repos)` spelled out.

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

    `existing_teams` maps EVERY DECLARED organization to its `reconcilers` team, or
    to None when the organization or the team is absent. Required and complete for
    the same reason `existing_repos` is a required mapping: the missing-key
    `KeyError` below is the loud failure, and the alternative -- treating an absent
    key as "fine" -- is how a comparison silently stops comparing. The team of an
    organization that does not exist yet is None, which is honest and lands it in
    `teams_to_converge` alongside the organization's own creation.

    TEAMS ARE PLANNED OVER THE DECLARED ORGANIZATIONS, NOT OVER THE ONES RECEIVING
    A REPOSITORY. That distinction is the entire defect this parameter closes: the
    grant belongs to the organization, not to the act of creating something in it,
    so a forge where every declared repository already exists still has teams to
    repair. See `team_needs_convergence`.

    `existing_repo_settings` maps `"org/name"` to the live `GET /repos/{o}/{r}`
    body for EVERY DECLARED repository, or to None when the forge does not hold it
    yet. Required and complete for the third time in this signature, and the reason
    has not changed: the missing-key `KeyError` is the loud failure, and an absent
    key treated as "fine" is how a comparison silently stops comparing. Here the
    silence would be particularly quiet -- a repository whose merge style was never
    set reads as a working repository, not as an empty field.

    `declared_settings` is separate from `declared` rather than folded into each
    `RepoSpec` because it is one block for the whole forge; see `RepoSettings` for
    why there is no per-repository override in this slice.
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

    # Sorted over the DECLARED organizations, so the plan reads in the same order
    # every run and a diff between two runs is a real change rather than dict order.
    teams_to_converge = tuple(sorted(org for org in declared_orgs if team_needs_convergence(existing_teams[org])))

    # OVER EVERY DECLARED REPOSITORY, INCLUDING THE ONES THIS RUN IS ABOUT TO
    # CREATE. A repository arrives with Gitea's permissive defaults whether it was
    # created empty or migrated, so scoping this to repositories that already exist
    # would leave every new one unconfigured until the NEXT run -- which is
    # lesson-424's shape read backwards: a convergence step scoped to the existing
    # set never reaches what the same run creates. `existing_repo_settings` holds
    # None for those, and `settings_needs_convergence` reads None as short.
    repos_to_configure = tuple(
        change
        for change in (
            SettingsChange(
                org=org,
                name=spec.name,
                changes=settings_changes(existing_repo_settings[f"{org}/{spec.name}"], declared_settings),
                absent=existing_repo_settings[f"{org}/{spec.name}"] is None,
            )
            for org, specs in sorted(declared.items())
            for spec in sorted(specs, key=lambda s: s.name)
        )
        if change.changes
    )

    # Reported, never acted on. The corollary ADR-065 D3 binds the reconciler to:
    # "import by accident must not become policy by inertia."
    undeclared_orgs = tuple(sorted(existing_orgs - declared_orgs))
    undeclared_repos = tuple(sorted(set(existing_repos) - declared_repos))

    # Only for repositories that EXIST. A declared-and-absent one is already in
    # `repos_to_create`/`repos_to_migrate` carrying its declared visibility, and
    # reporting drift on something that does not exist yet would be reporting the
    # plan back to itself.
    visibility_drift = tuple(
        VisibilityDrift(
            org=org,
            name=spec.name,
            declared_private=spec.private,
            live_private=existing_repos[f"{org}/{spec.name}"],
        )
        for org, specs in sorted(declared.items())
        for spec in sorted(specs, key=lambda s: s.name)
        if f"{org}/{spec.name}" in existing_repos and existing_repos[f"{org}/{spec.name}"] != spec.private
    )

    return ReconcilePlan(
        orgs_to_create=orgs_to_create,
        repos_to_create=repos_to_create,
        repos_to_migrate=repos_to_migrate,
        teams_to_converge=teams_to_converge,
        repos_to_configure=repos_to_configure,
        undeclared_orgs=undeclared_orgs,
        undeclared_repos=undeclared_repos,
        visibility_drift=visibility_drift,
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


def load_settings(common: Mapping[str, Any]) -> RepoSettings:
    """Read `gitea.repository_settings` out of a parsed common.yaml.

    REFUSES AN ABSENT BLOCK, rather than defaulting. That is the opposite of
    `load_declaration`, which treats an absent `organizations` as an empty dict,
    and the asymmetry is deliberate: an empty declaration means "reconcile nothing"
    and is a coherent state, while an absent settings block would mean "compare
    nothing" -- silently switching off the check on every repository. That is the
    defect this function exists to prevent, wearing the costume of a sensible
    default.

    UNCONDITIONALLY, with no "…unless nothing is declared" branch. The first draft
    had one, returning Gitea's live defaults as a harmless sentinel for an empty
    forge. It was not harmless: it was a fabricated declaration, indistinguishable
    at every call site from one an operator wrote, and the whole point of the
    refusal is that no such value exists. The caller reaches this only after its own
    empty-declaration guard, so totality buys nothing here.

    A DEFAULT WOULD BE WORSE THAN THE ABSENCE, because it would have to be either
    Gitea's permissive values (converging the forge onto exactly what #1633 was
    filed about) or an opinion invented here (an SSOT whose real source is a Python
    literal). Neither is a declaration.

    Unknown keys raise `TypeError` from the dataclass rather than being ignored: a
    typo'd key that were dropped would leave a field silently unmanaged, and one
    that reached the PATCH body would make the repository fail to converge forever
    -- Gitea accepting the call and the next run finding the same drift.
    """
    gitea = (common.get("apps", {}).get("services", {}).get("core", {}).get("gitea", {})) or {}
    block = gitea.get("repository_settings")

    if not block:
        raise ValueError(
            "`apps.services.core.gitea.repository_settings` is absent. It is required rather "
            "than defaulted: repository settings do NOT survive "
            "`POST /repos/migrate`, so a migrated repository arrives configured with Gitea's "
            "permissive defaults — measured 2026-09-04, `default_merge_style: merge` on all three "
            "against a GitHub original that was squash-only. Defaulting here would converge the "
            "forge onto exactly the state #1633 was filed about, and do it silently."
        )

    known = {f.name for f in fields(RepoSettings)}
    unknown = sorted(set(block) - known)
    if unknown:
        raise ValueError(
            f"`repository_settings` contains unknown key(s) {unknown}. Field names are Gitea's own "
            f"`EditRepoOption` names, so a misspelling is not a new setting — it is a field left "
            f"unmanaged, or a PATCH body Gitea accepts and ignores, which makes the repository fail "
            f"to converge on every future run. Known: {sorted(known)}."
        )
    missing = sorted(known - set(block))
    if missing:
        raise ValueError(
            f"`repository_settings` is missing {missing}. Every field is declared explicitly, with "
            f"no partial block: a field omitted here is a field whose value is whatever the forge "
            f"happens to hold, which is the reproducibility hole the declaration exists to close "
            f"(the same reasoning as `private:` on each repository)."
        )
    return RepoSettings(**{key: block[key] for key in known})


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
    # Named as a repair rather than as a creation, because it usually is one: the
    # team exists and grants write over nothing. "widen" is the verb `edit_team`
    # is restricted to, so the line also says what will NOT happen.
    for team_org in plan.teams_to_converge:
        lines.append(f"  ~ team {team_org}/{TEAM_NAME}   widen to the full grant over all repositories")
    # Field by field, because this is the line an operator approves `--apply` on and
    # "settings differ" is not a basis for approving anything. A repository that does
    # not exist yet gets a count instead of nine `None -> x` rows, so the one
    # repository whose live settings actually drifted stays visible.
    for change in plan.repos_to_configure:
        if change.absent:
            lines.append(
                f"  ~ settings {change.full_name}   apply all {len(change.changes)} declared settings (new repository)"
            )
            continue
        for key, live_value, declared_value in change.changes:
            lines.append(f"  ~ settings {change.full_name}   {key}: {live_value!r} -> {declared_value!r}")
    # Distinct names from the loops above, and not only for style: the created
    # entries are `DeclaredRepo`s while the strays are `"org/name"` strings, so
    # reusing `repo` shadows one type with the other and mypy refuses it.
    for stray_org in plan.undeclared_orgs:
        lines.append(f"  ? org  {stray_org}   undeclared — reported, not removed")
    for stray_repo in plan.undeclared_repos:
        lines.append(f"  ? repo {stray_repo}   undeclared — reported, not removed")
    # Spelled out both ways rather than as "drift": an operator reading this has to
    # decide whether the declaration or the forge is wrong, and "declared private,
    # forge has it public" says which direction to look. "differs" would not.
    for drift in plan.visibility_drift:
        want = "private" if drift.declared_private else "public"
        got = "private" if drift.live_private else "public"
        lines.append(f"  ! repo {drift.full_name}   declared {want}, forge has it {got} — reported, not changed")
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


def team_needs_convergence(team: Mapping[str, Any] | None) -> bool:
    """Does this team fall short of the grant `create_team`/`edit_team` would give it?

    ONE PREDICATE, TWO CALLERS, AND THAT IS THE POINT. `plan_reconcile` asks it to
    decide whether the run has work to do; `ensure_team` asks it to decide whether
    to call `edit_team`. If they were separate expressions the plan could report a
    converged forge while `execute` still had a repair to make -- or, as measured on
    prod 2026-09-03, the reverse: `ensure_team` held a correct repair that nothing
    ever reached, because the only thing that decided whether it ran was whether a
    repository was being created.

    That is the defect this exists to close, and it is worth naming as a class: **a
    convergence step scoped to the creation diff never repairs what already exists.**
    `execute` iterated the organizations RECEIVING a new repository, so on a forge
    where everything declared already existed the set was empty, `is_noop` was True,
    and the CLI returned before `execute` was called at all. Both live teams kept
    `includes_all_repositories: False` -- write over zero repositories -- across
    every green run.

    EVERY FIELD `edit_team` SENDS IS CHECKED, not only the one that was wrong. A
    predicate covering a subset of the grant is the same defect one field over: the
    plan would report a match on a team whose `can_create_org_repo` was unset, and
    `ensure_team` would then raise on a run that claimed there was nothing to do.
    So the list here and the payload there are the same list, derived from
    `TEAM_UNITS` rather than restated.

    An absent team needs convergence too. `create_team` is the repair in that case,
    and the caller that acts on this does not need to know which of the two it is.
    """
    if team is None:
        return True
    if not team.get("includes_all_repositories"):
        return True
    if not team.get("can_create_org_repo"):
        return True
    units = team.get("units_map") or {}
    return any(units.get(unit) != TEAM_PERMISSION for unit in TEAM_UNITS)


class RepoSettingsError(Exception):
    """A repository was configured, and did not come back configured.

    Its own category for the same reason `TeamPermissionError` is: the failure is
    silent by nature. Gitea answers 200 to a PATCH whose fields it did not apply --
    an unknown key, a value it declines, a permission that stops short of the field
    -- so a run trusting the response would report a converged forge that still
    merges with merge commits, and the next run would find the same drift and
    report success again, forever.
    """


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
    repos_configured: list[str] = field(default_factory=list)
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
    #
    # The condition is `team_needs_convergence` and not an inline field test, so
    # that the plan's decision to schedule this org and this function's decision to
    # act cannot disagree. They did, in the other direction, until 2026-09-03.
    if team_needs_convergence(team):
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


def ensure_settings(configurator: GiteaBasicAuthClient, repo: SettingsChange, declared: RepoSettings) -> dict[str, Any]:
    """PATCH a repository's settings, then READ THEM BACK and assert they took.

    THE RE-READ IS THE POINT, exactly as in `ensure_team`, and the same measurement
    is behind it: a create-team response reported `permission: write` on a team that
    granted nothing. Gitea's PATCH answers 200 with a repository body, and that body
    is the artefact whose trustworthiness is in question -- so the assertion is made
    against a fresh `GET`, not against what the write returned.

    THE POST-CONDITION IS `settings_needs_convergence` ITSELF, not a hand-written
    field list. A separate list here would be a third expression of the same
    question, free to fall behind the declaration -- and the failure mode of falling
    behind is a field that is never checked, which is the one this module keeps
    finding. Reusing the predicate makes "what the plan schedules", "what the PATCH
    sends" and "what is verified afterwards" the same set by construction.
    """
    configurator.edit_repo(repo.org, repo.name, declared.to_api_payload())

    live = configurator.get_repo(repo.org, repo.name)
    if live is None:
        raise RepoSettingsError(
            f"{repo.full_name} does not read back after being configured. The PATCH was "
            f"accepted, so this is not a permission problem — the repository is gone or the read "
            f"credential lost sight of it."
        )
    remaining = settings_changes(live, declared)
    if remaining:
        detail = ", ".join(
            f"{key}: live {live_value!r}, declared {declared_value!r}" for key, live_value, declared_value in remaining
        )
        raise RepoSettingsError(
            f"{repo.full_name} was configured and did not converge — {detail}. Gitea answered the "
            f"PATCH without applying these, which it does silently: a 200 here says the request was "
            f"accepted, never that the settings changed."
        )
    return live


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
    declared_settings: RepoSettings,
    migration_token: str | None = None,
    migrator: GiteaClient | None = None,
    configurator: GiteaBasicAuthClient | None = None,
) -> ExecutionReport:
    """Carry out a plan, with each operation performed by the credential that may.

    TWO CLIENTS, NOT ONE, and the split is the acceptance criterion rather than a
    style choice: `admin` creates organizations because Gitea puts the creator in
    `Owners` and ADR-065 D1 requires the bot to own nothing; `bot` creates
    repositories inside them, which confers no ownership. `actor_for_org_creation`
    and `actor_for_repo_creation` encode the same answer for the test suite.

    FOUR, COUNTING THE TWO THE SUPERADMIN'S PASSWORD CARRIES. `migrator` and
    `configurator` are optional in the signature and mandatory in effect: each is
    required exactly when the plan contains work of its kind, and its absence is
    reported per repository rather than raised, so a run says which repositories it
    could not reach instead of stopping at the first. They are the same client in
    practice -- one `GiteaBasicAuthClient` on one credential -- and are separate
    parameters because they are separate capabilities, and a later change that
    narrows one should not silently widen the other.

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
    #
    # UNIONED WITH `teams_to_converge`, which is what makes a repair reachable on a
    # forge that needs no repository created. `receiving` alone scoped this step to
    # the creation diff, so an organization whose team was wrong and whose
    # repositories all existed was never visited -- and the CLI never even called
    # `execute`, because such a plan was `is_noop`.
    receiving = {repo.org for repo in plan.repos_to_create} | {repo.org for repo in plan.repos_to_migrate}
    for org in sorted((receiving | set(plan.teams_to_converge)) - failed_orgs):
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

    # LAST, AND AFTER THE CREATES AND MIGRATES ON PURPOSE. A repository this run
    # brought into existence arrives with Gitea's permissive defaults, so it needs
    # configuring in the SAME run -- the plan already scheduled it, because
    # `settings_needs_convergence(None, ...)` is True. Running this first would PATCH
    # a repository that did not exist yet.
    #
    # Skipped for anything this run failed to produce, which is why the two sets are
    # subtracted rather than the plan trusted: a repository whose migration failed is
    # absent, and PATCHing it would turn one reported failure into two, the second
    # naming a symptom instead of the cause.
    failed_repos = {target.removeprefix("repo ") for target, _ in report.failures if target.startswith("repo ")} | {
        f"{repo.org}/{repo.name}" for repo in plan.repos_to_create + plan.repos_to_migrate if repo.org in failed_orgs
    }
    # `change`, not `repo`: `repos_to_configure` holds `SettingsChange`s while the
    # loops above hold `DeclaredRepo`s, and reusing the name shadows one type with
    # the other -- which mypy refuses, for the same reason `format_plan` names its
    # stray loops apart.
    for change in plan.repos_to_configure:
        full_name = change.full_name
        if full_name in failed_repos:
            continue
        if configurator is None:
            _handle_failure(
                report,
                f"settings {full_name}",
                RuntimeError(
                    "no configurator client was supplied. Repository settings are the second "
                    "operation here that no token may perform — measured 2026-09-04 with a no-op "
                    "PATCH against all three declared repositories: admin token 403 "
                    "required=[write:repository] on every one, bot token 403 'owner or a "
                    "collaborator with admin write' on the two it did not create, superadmin basic "
                    "auth 200 on all three. So the caller must pass a GiteaBasicAuthClient."
                ),
            )
            continue
        try:
            ensure_settings(configurator, change, declared_settings)
            report.repos_configured.append(full_name)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, whatever its type
            _handle_failure(report, f"settings {full_name}", exc)

    return report
