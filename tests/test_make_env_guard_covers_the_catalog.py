"""A Make wrapper may not accept fewer environments than the thing it wraps.

`test_make_env_guard_rejects_dev.py` (#1672) fixed eighteen vacuous `test -n
"$(ENV)"` guards by filtering the value against the environments each target
accepts. That was right, and for `import-n8n` it took the environment list from
the target's own **usage string** -- `"Usage: make import-n8n ENV=staging"` --
rather than from the catalog the command reads. All four specs in
`N8N_IMPORT_CATALOG` declare `envs={"staging", "prod"}`, and `toolkit infra n8n
import` refuses only `dev`, so `make import-n8n ENV=prod` printed a usage line
for a run that is supported, implemented and (measured 2026-09-05) works.

The failure is quiet in the direction that matters. A guard that is too LOOSE
gets caught the first time something runs where it should not. A guard that is
too TIGHT looks like correct input validation: the operator reads "Usage:
ENV=staging", believes prod is unsupported, and either gives up or reaches past
the Makefile -- which is how a documented deploy path stops being the one people
use. Nothing goes red, because refusing to run cannot fail a test that only
checks that running works.

So the floor is DERIVED from the catalog rather than restated here. A test that
hardcoded `{"staging", "prod"}` would agree with today's catalog and drift the
moment a workflow declares a third environment -- reintroducing exactly the
"help text as specification" mistake one level up.
"""

from __future__ import annotations

import pathlib
import re

from toolkit.features.n8n_import import N8N_IMPORT_CATALOG

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

#: `dev` is refused by the CLI itself ("Dev environment uses Docker Compose, not
#: K8s"), so it is excluded from the floor no matter what a spec declares.
CLI_REFUSES = frozenset({"dev"})


def _filter_envs(target: str) -> set[str]:
    """The environments `target`'s ENV guard actually admits."""
    recipe = re.search(
        rf"^{re.escape(target)}:.*?\n((?:\t.*\n)+)",
        MAKEFILE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert recipe, f"no recipe found for `{target}` — the scan has drifted"

    guard = re.search(r'test -n "\$\(filter \$\(ENV\),([a-z ]+)\)"', recipe.group(1))
    assert guard, (
        f"`{target}` has no `$(filter $(ENV),...)` guard. If the guard was removed, "
        f"this test cannot measure anything — see test_make_env_guard_rejects_dev.py "
        f'for why the `test -n "$(ENV)"` form is dead.'
    )
    return set(guard.group(1).split())


def test_the_catalog_declares_something_to_check() -> None:
    """Anti-vacuity. An empty catalog makes every assertion below a pass, and an
    empty expectation is not a weak expectation — it matches everything."""
    declared = {env for spec in N8N_IMPORT_CATALOG for env in spec.envs} - CLI_REFUSES
    assert len(declared) >= 2, (
        f"the import catalog declares only {sorted(declared)}; with fewer than two "
        f"environments the superset check below cannot distinguish a correct guard "
        f"from one that names a single env by accident"
    )


def test_import_n8n_accepts_every_env_its_catalog_declares() -> None:
    """Superset, never equality.

    Equality would fail the day a target legitimately accepts an environment no
    workflow targets yet, and a test that fails for a correct reason is a test
    someone loosens. What must never happen is the guard admitting FEWER
    environments than the command supports.
    """
    declared = {env for spec in N8N_IMPORT_CATALOG for env in spec.envs} - CLI_REFUSES
    accepted = _filter_envs("import-n8n")

    missing = declared - accepted
    assert not missing, (
        f"`make import-n8n` refuses {sorted(missing)}, which the import catalog declares "
        f"as supported (guard admits {sorted(accepted)}; catalog declares {sorted(declared)}).\n\n"
        f"The wrapper is narrower than the command it wraps, so a supported run is "
        f"unreachable through the documented path and the operator is told it is "
        f"unsupported. Take the environments from `N8N_IMPORT_CATALOG`, never from the "
        f"target's usage string — that string is help text, not a specification."
    )


def test_the_guard_still_rejects_something() -> None:
    """A floor is only a floor if a value outside it fails.

    Widening the filter until it admits everything would satisfy the superset
    check above and reinstate the vacuous guard #1672 removed, one indirection
    along.
    """
    accepted = _filter_envs("import-n8n")
    assert "dev" not in accepted, (
        "`make import-n8n ENV=dev` would now be admitted by the guard and refused only "
        "later by the CLI. `dev` is Docker Compose, not K8s — the guard is where that "
        "is supposed to be said."
    )
    assert accepted, "the guard admits no environment at all, so the target can never run"
