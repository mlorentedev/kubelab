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
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


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
