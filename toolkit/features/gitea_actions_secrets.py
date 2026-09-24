"""Repository Actions secrets on the forge, delivered one way from SOPS (TOOL-062, #1626).

Gitea resolves an unset Actions secret to an EMPTY STRING, not an error. A
migrated workflow that reads one therefore fails later, somewhere that does not
name the cause -- or succeeds having done nothing. Nothing wrote these secrets
before this module, and the values could not be carried over from GitHub: both
forges return names and timestamps, never a value.

SOPS REMAINS THE ONLY SOURCE. The catalog declares what goes where
(`SecretSpec.forge_actions`); this module plans and performs the copy. There is
no reverse mode and no deletion -- a secret on the forge that the catalog does
not declare is reported, never removed, for the reason TOOL-035 gives the
repository reconciler: removal is a decision, not a convergence.

THE SPLIT IS THE SAME AS `gitea_repos`. `plan_actions_secrets` is pure: targets,
the live names and the set of key paths that hold a value go in; a plan comes
out; no network and NO VALUES. The planner is handed which keys are valued, not
what they hold, so a plan -- and anything formatted or logged from one -- cannot
carry a credential by construction. `execute_actions_secrets` is the only code
that ever sees a value, and only long enough to send it.

WHAT CONVERGENCE MEANS HERE IS WEAKER THAN ELSEWHERE, and saying so is the point.
The API returns a secret's name, never its value and never an `updated_at`. So a
second run reporting nothing to do proves the NAMES exist -- not that a value
rotated in SOPS last week ever reached the forge. `force=True` re-sends every
declared secret; it is the only way a rotation lands, and the formatted plan says
so next to every secret it cannot verify. The other half of the guarantee lives
in the consuming workflow, which refuses to run with an empty input: only inside
the job can a secret be checked by consequence (#1626, design comment).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Collection, Iterable, Mapping, Protocol

from toolkit.config.constants import is_placeholder
from toolkit.features.secrets_manager import SecretSpec, forge_actions_secret_name


@dataclass(frozen=True)
class SecretTarget:
    """One secret bound for one repository. Carries a SOPS path, never a value."""

    repo: str  # `org/name`
    name: str  # the Actions secret name, always via forge_actions_secret_name()
    key_path: str  # where the value lives in SOPS

    @property
    def owner(self) -> str:
        return self.repo.split("/", 1)[0]

    @property
    def repo_name(self) -> str:
        return self.repo.split("/", 1)[1]


def delivery_targets(catalog: Iterable[SecretSpec]) -> tuple[SecretTarget, ...]:
    """Every (repository, secret) pair the catalog declares, in catalog order."""
    return tuple(
        SecretTarget(repo=repo, name=forge_actions_secret_name(spec.key_path), key_path=spec.key_path)
        for spec in catalog
        for repo in spec.forge_actions
    )


def sops_value(config: Mapping[str, Any], key_path: str) -> str:
    """A dotted SOPS path's value, or '' when absent, non-scalar or a placeholder.

    A placeholder counts as absent. Pushing `CHANGEME` would give the workflow a
    non-empty secret that its empty-input preflight lets through, which is worse
    than no secret at all: the failure moves to the provider's API, which does
    not say which of four values was the wrong one.
    """
    node: object = config
    for part in key_path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return ""
        node = node[part]
    if node is None or isinstance(node, (Mapping, list)) or is_placeholder(node):
        return ""
    return str(node)


@dataclass(frozen=True)
class ActionsSecretsPlan:
    """What a run would do. Writes and reports -- there is no field a deletion could travel in."""

    to_create: tuple[SecretTarget, ...] = ()
    to_overwrite: tuple[SecretTarget, ...] = ()  # only with force=True
    present: tuple[SecretTarget, ...] = ()  # the name exists; the value cannot be checked
    missing_values: tuple[SecretTarget, ...] = ()  # declared, and SOPS holds nothing for it
    unreachable: tuple[SecretTarget, ...] = ()  # the forge could not list the repository
    undeclared: tuple[tuple[str, str], ...] = ()  # (repo, name) on the forge, not in the catalog

    @property
    def is_noop(self) -> bool:
        """True when `execute` would write nothing. Reports alone are not work."""
        return not self.to_create and not self.to_overwrite

    @property
    def is_complete(self) -> bool:
        """True when every declared secret has a source and a repository to land in.

        Separate from `is_noop` because the two fail in opposite directions: a plan
        can have nothing to write BECAUSE a value is missing, and reading that as
        "converged" is the silent pass this module exists to prevent.
        """
        return not self.missing_values and not self.unreachable


def plan_actions_secrets(
    targets: Iterable[SecretTarget],
    live: Mapping[str, set[str] | None],
    valued: Collection[str],
    force: bool = False,
) -> ActionsSecretsPlan:
    """Compare the declaration with the forge. Pure: no network, and no values.

    `live` maps each repository to the secret names the forge lists for it, or to
    None when it could not answer (absent repository). A repository missing from
    the mapping is treated the same way: not asked is not the same as empty.
    `valued` is the set of key paths SOPS holds a non-empty value for.
    """
    create: list[SecretTarget] = []
    overwrite: list[SecretTarget] = []
    present: list[SecretTarget] = []
    missing: list[SecretTarget] = []
    unreachable: list[SecretTarget] = []
    declared_names: dict[str, set[str]] = {}

    for target in targets:
        declared_names.setdefault(target.repo, set()).add(target.name)
        names = live.get(target.repo)
        if names is None:
            unreachable.append(target)
        elif target.key_path not in valued:
            missing.append(target)
        elif target.name in names:
            (overwrite if force else present).append(target)
        else:
            create.append(target)

    undeclared = tuple(
        (repo, name)
        for repo in sorted(live)
        for name in sorted((live[repo] or set()) - declared_names.get(repo, set()))
    )
    return ActionsSecretsPlan(
        to_create=tuple(create),
        to_overwrite=tuple(overwrite),
        present=tuple(present),
        missing_values=tuple(missing),
        unreachable=tuple(unreachable),
        undeclared=undeclared,
    )


def format_actions_secrets_plan(plan: ActionsSecretsPlan) -> str:
    """The plan for a terminal. Names and SOPS paths only -- the plan holds nothing else."""
    lines: list[str] = []
    for t in plan.to_create:
        lines.append(f"  + {t.repo}  {t.name}  (create, from {t.key_path})")
    for t in plan.to_overwrite:
        lines.append(f"  ~ {t.repo}  {t.name}  (re-push, --force)")
    for t in plan.present:
        lines.append(
            f"  = {t.repo}  {t.name}  exists; its value cannot be read back, so re-push with "
            f"--force after rotating {t.key_path}"
        )
    for t in plan.missing_values:
        lines.append(f"  ! {t.repo}  {t.name}  NO VALUE at {t.key_path} in SOPS -- not written")
    for t in plan.unreachable:
        lines.append(f"  ! {t.repo}  {t.name}  the forge has no such repository -- not written")
    for repo, name in plan.undeclared:
        lines.append(f"  ? {repo}  {name}  not declared in the catalog -- reported, never deleted")
    return "\n".join(lines) if lines else "  (no Actions secrets declared)"


class SecretWriter(Protocol):
    def put_actions_secret(self, owner: str, name: str, secret_name: str, value: str) -> None: ...


@dataclass
class ActionsSecretsReport:
    written: list[SecretTarget] = field(default_factory=list)
    failed: list[tuple[SecretTarget, str]] = field(default_factory=list)


def execute_actions_secrets(
    plan: ActionsSecretsPlan,
    forge: SecretWriter,
    value_of: Callable[[str], str],
) -> ActionsSecretsReport:
    """Write the planned secrets. The one place a value exists, and only in the call.

    Each failure is recorded against its secret and the rest still run, so a run
    says which secrets it could not land instead of stopping at the first. A value
    that turns out empty at write time is refused here too, even though the
    planner already excluded it: the planner and this function read SOPS at
    different moments, and pushing '' is the exact failure this module prevents.
    """
    report = ActionsSecretsReport()
    for target in (*plan.to_create, *plan.to_overwrite):
        value = value_of(target.key_path)
        if not value:
            report.failed.append((target, f"no value at {target.key_path} when writing; not sent"))
            continue
        try:
            forge.put_actions_secret(target.owner, target.repo_name, target.name, value)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, whatever its type
            report.failed.append((target, str(exc)))
            continue
        report.written.append(target)
    return report
