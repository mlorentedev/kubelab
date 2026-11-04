"""A dev-only Makefile target refuses an ENV other than dev (#3069).

These targets run the Docker Compose stack with `--env dev` whatever `ENV`
says, and `make` never rejects a variable a recipe does not read. Measured
2026-11-03: `make smoke-test ENV=prod`, run to check a prod deploy, read dev,
printed `No services to check.` and exited 0. So every recipe that passes
`--env dev` must begin with `$(call require_dev_env,...)`.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"

_TARGET = re.compile(r"^([A-Za-z0-9_.-]+):(?!=)")


def _recipes() -> dict[str, list[str]]:
    recipes: dict[str, list[str]] = {}
    current: str | None = None
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        match = _TARGET.match(line)
        if match:
            current = match.group(1)
            recipes[current] = []
        elif line.startswith("\t") and current:
            recipes[current].append(line)
        elif line.strip() and not line.startswith("#") and not line.startswith("\t"):
            current = None
    return recipes


def _prerequisites() -> dict[str, list[str]]:
    prereqs: dict[str, list[str]] = {}
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        match = _TARGET.match(line)
        if match:
            rest = line[match.end() :].split("|")[0]
            prereqs[match.group(1)] = rest.split()
    return prereqs


def _dev_only() -> dict[str, list[str]]:
    """Recipes passing `--env dev`, plus every target reaching one through a prerequisite."""
    recipes = _recipes()
    found = {name for name, lines in recipes.items() if any("--env dev" in line for line in lines)}
    prereqs = _prerequisites()
    grew = True
    while grew:
        reached = {name for name, deps in prereqs.items() if name not in found and found & set(deps)}
        grew = bool(reached)
        found |= reached
    return {name: recipes.get(name, []) for name in found}


def test_the_scan_finds_the_dev_only_targets() -> None:
    """A reformatted recipe must not reduce this suite to zero assertions."""
    direct = {"smoke-test", "up-dev", "down-dev", "build-dev", "setup-certs"}
    through_prerequisites = {"dev-full-clean", "dev-full-reset"}
    assert direct | through_prerequisites <= set(_dev_only())


def test_every_dev_only_target_refuses_another_env() -> None:
    unguarded = [name for name, lines in _dev_only().items() if not lines or "$(call require_dev_env" not in lines[0]]
    assert not unguarded, f"runs --env dev without $(call require_dev_env,...) first: {unguarded}"


def test_dev_only_targets_have_no_prerequisite_that_runs_beside_the_guard() -> None:
    """Under `make -j` a prerequisite runs alongside the guard, not after it.

    So a dev-only target may only depend on other dev-only targets, which carry
    the guard themselves; anything else (credentials-generate writes SOPS for
    whatever ENV says) is invoked from the recipe, after the guard.
    """
    dev_only = _dev_only()
    prereqs = _prerequisites()
    stray = {name: [d for d in prereqs.get(name, []) if d not in dev_only] for name in dev_only}
    stray = {name: deps for name, deps in stray.items() if deps}
    assert not stray, f"prerequisites that are not guarded dev-only targets: {stray}"


def test_smoke_test_with_prod_fails_and_names_the_check_to_run() -> None:
    if shutil.which("make") is None:
        pytest.skip("make not on PATH: cannot run the target (a skip is CANNOT CHECK, not OK)")
    done = subprocess.run(
        ["make", "--no-print-directory", "smoke-test", "ENV=prod"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert done.returncode != 0
    assert "make test-e2e ENV=prod" in done.stderr


def test_setup_says_which_env_it_ignores() -> None:
    """`setup` pins its cert step to dev; with another ENV it says so instead of ignoring it silently."""
    lines = _recipes()["setup"]
    pin = next(i for i, line in enumerate(lines) if "setup-certs ENV=dev" in line)
    assert any('test "$(ENV)" = dev ||' in line and "does not apply" in line for line in lines[:pin]), lines
