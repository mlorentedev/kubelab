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


def _dev_only() -> dict[str, list[str]]:
    return {name: lines for name, lines in _recipes().items() if any("--env dev" in line for line in lines)}


def test_the_scan_finds_the_dev_only_targets() -> None:
    """A reformatted recipe must not reduce this suite to zero assertions."""
    assert {"smoke-test", "up-dev", "down-dev", "build-dev", "setup-certs"} <= set(_dev_only())


def test_every_dev_only_target_refuses_another_env() -> None:
    unguarded = [name for name, lines in _dev_only().items() if "$(call require_dev_env" not in lines[0]]
    assert not unguarded, f"runs --env dev without $(call require_dev_env,...) first: {unguarded}"


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
