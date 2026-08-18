"""Static guards on `make config-check-drift`: what it reverts, and what it checks.

#1034 is the revert half; #1118 is the env half. Both failed the same way — a
step that looks like a control in review while being incapable of acting.

`make config-check-drift` regenerates config into the working tree and reverts
it afterwards. The revert used to be `git checkout -- infra edge` — two whole
top-level trees — so it discarded any uncommitted hand edit under them,
including `infra/config/values/*.yaml`, the repo's declared source of truth. It
destroyed real work while printing `✓ No drift`, and `git checkout --` on
unstaged changes is the one git operation that leaves no reflog entry and no
stash.

The property that matters is not which specific directories are listed; it is
that **every entry is generator output**. A future edit that widens the variable
back toward a source tree reintroduces the exact defect, and the widening would
look reasonable in review — the original did.

The env half: the target only has something to diff for environments with a
committed K8s overlay. Pointed anywhere else it runs `git diff` over a pathspec
that matches nothing, which exits 0 — indistinguishable from agreement. Two
guards shipped that let exactly that happen (#1118), so the allow-list itself is
now the thing under test.

Deliberately static: it parses the Makefile rather than running the target, so
it needs no cluster, no age key and no generator run, and it fails in CI on the
diff that introduces the regression rather than on the day someone loses work.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

VARIABLE = "DRIFT_REVERT_PATHS"
ENV_VARIABLE = "DRIFT_ENVS"

#: The path component that marks a directory as generator output. Every entry
#: in the revert set must contain it.
GENERATED_MARKER = "generated"


def _declared_revert_paths() -> list[str]:
    """Parse `DRIFT_REVERT_PATHS` from the Makefile, honouring `\\` continuations."""
    text = MAKEFILE.read_text()
    match = re.search(
        rf"^{VARIABLE}\s*:?=\s*((?:.*\\\n)*.*)$",
        text,
        re.MULTILINE,
    )
    if match is None:
        pytest.fail(
            f"{VARIABLE} not found in Makefile. If the revert was inlined back "
            "into the recipe, this guard is silently no longer guarding "
            "anything — see #1034."
        )
    raw = match.group(1).replace("\\\n", " ")
    return [p for p in raw.split() if p]


def test_revert_paths_are_declared() -> None:
    """Guard the parse itself, so the assertions below cannot pass vacuously."""
    assert _declared_revert_paths(), f"{VARIABLE} parsed as empty"


def test_every_revert_path_is_generator_output() -> None:
    """The invariant: the revert can only ever discard generated files."""
    offenders = [p for p in _declared_revert_paths() if GENERATED_MARKER not in pathlib.PurePath(p).parts]
    assert not offenders, (
        "These revert paths are not generator output, so `git checkout --` on "
        f"them can discard hand-written work (#1034): {offenders}"
    )


def test_revert_paths_exist_and_are_tracked_directories() -> None:
    """A path git does not track cannot be reverted — it would only error.

    The three gitignored output directories (`edge/traefik/generated`,
    `infra/ansible/generated`, `infra/config/authelia/generated`) are excluded
    from the revert set for exactly this reason. Listing one would bring back
    the `2>/dev/null || true` that hid the original failure.
    """
    for path in _declared_revert_paths():
        resolved = REPO_ROOT / path
        assert resolved.is_dir(), f"{path} is not a directory in the repo"
        tracked = list(resolved.glob("*.yaml"))
        assert tracked, f"{path} holds no generated manifests — is it still the right path?"


def test_recipe_reverts_through_the_variable() -> None:
    """The recipe must use the variable, not an inline pathspec.

    Without this, `DRIFT_REVERT_PATHS` could stay correct while the recipe
    quietly reverted something else, and the two tests above would still pass.
    """
    text = MAKEFILE.read_text()
    recipe = text[text.index("config-check-drift:") :]
    recipe = recipe[: recipe.index("\n.PHONY")] if "\n.PHONY" in recipe else recipe

    checkouts = [ln.strip() for ln in recipe.splitlines() if "git checkout" in ln]
    assert checkouts, "config-check-drift no longer reverts at all"
    for line in checkouts:
        assert f"$({VARIABLE})" in line, (
            f"revert does not go through {VARIABLE}: {line!r} — an inline pathspec is how #1034 shipped"
        )
        assert "2>/dev/null" not in line and "|| true" not in line, (
            f"revert silences its own failure: {line!r} — a destructive step that cannot fail cannot be audited (#1034)"
        )


def _declared_drift_envs() -> list[str]:
    """Parse `DRIFT_ENVS` from the Makefile."""
    text = MAKEFILE.read_text()
    match = re.search(rf"^{ENV_VARIABLE}\s*:?=\s*(.*)$", text, re.MULTILINE)
    if match is None:
        pytest.fail(
            f"{ENV_VARIABLE} not found in Makefile. The drift gate's env guard was "
            "inlined or removed — see #1118/#PR_PLACEHOLDER."
        )
    return match.group(1).split()


def test_recipe_guards_env_through_the_variable() -> None:
    """The env guard must validate against `DRIFT_ENVS`, not re-derive the list.

    Two weaker guards shipped before and both were reachable no-ops: `test -n
    "$(ENV)"` always saw the repo-wide `ENV ?= dev`, and `test "$(origin ENV)" =
    "command line"` accepted both `ENV=` and `ENV=dev`. Either lets the gate run
    against an environment with no committed overlay, where `git diff` over a
    pathspec matching nothing exits 0 and prints "no drift" whatever the
    generator did. Widening the guard back would look reasonable in review — the
    two that shipped did.
    """
    text = MAKEFILE.read_text()
    recipe = text[text.index("config-check-drift:") :]
    recipe = recipe[: recipe.index("\n.PHONY")] if "\n.PHONY" in recipe else recipe

    assert f"$({ENV_VARIABLE})" in recipe, (
        f"the env guard no longer references {ENV_VARIABLE} — an allow-list the "
        "recipe does not consult guards nothing (#1118)"
    )
    assert "$(origin ENV)" not in recipe, (
        "the guard is back to testing where ENV came from rather than what it "
        "is; `ENV=` and `ENV=dev` both pass that test (#1118)"
    )
    assert "$(words $(ENV))" in recipe, (
        "the arity check is gone — `$(filter)` alone accepts ENV='staging prod' "
        "and splices both words unquoted into the generator's argv"
    )


def test_every_drift_env_has_a_revert_path() -> None:
    """The two lists must stay in step, since neither derives from the other.

    `DRIFT_REVERT_PATHS` is deliberately literal so the assertions above can
    check the paths exist on disk. That leaves the pair free to diverge: an env
    added to `DRIFT_ENVS` without a revert path would be regenerated and never
    cleaned up, and a revert path for an env the guard rejects is dead weight.
    """
    envs = _declared_drift_envs()
    assert envs, f"{ENV_VARIABLE} parsed as empty"

    reverts = _declared_revert_paths()
    for env in envs:
        assert any(env in pathlib.PurePath(p).parts for p in reverts), (
            f"{ENV_VARIABLE} allows '{env}' but no {VARIABLE} entry covers it — "
            "the gate would regenerate that overlay and leave it dirty"
        )
    for path in reverts:
        assert any(env in pathlib.PurePath(path).parts for env in envs), (
            f"{VARIABLE} reverts '{path}' but {ENV_VARIABLE} allows no such env"
        )
