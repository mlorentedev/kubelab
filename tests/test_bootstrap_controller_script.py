"""Guards for `scripts/bootstrap-controller.sh`.

The script installs the tools that `make` cannot install, because `make` is one
of them: GNU make and Poetry, then it hands off to `make setup-ansible` for the
venv, the collection pins and the doctor. A bootstrap script is the one file in
a repo that is allowed to duplicate a version, since it has to run before the
lockfile can be read — so what these tests protect is that the duplication stays
honest:

- the Poetry pin still satisfies `poetry.lock`, and the Python floor still
  matches `pyproject.toml`, so the copy cannot drift from the SSOT it mirrors;
- `--check` really reports and installs nothing, since that is the mode the
  runbook tells a cautious operator to run first;
- the Windows guard fires, because that shell is the failure this whole ticket
  exists to name, and a guard that never runs is a comment.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/bootstrap-controller.sh"
RUNBOOK = REPO / "docs/runbooks/ansible-controller.md"


def _pin(name: str) -> str:
    """Read a `NAME="value"` constant out of the script."""
    match = re.search(rf'^{name}="([^"]+)"$', SCRIPT.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{name} is not declared in scripts/bootstrap-controller.sh"
    return match.group(1)


def _major_minor(version: str) -> tuple[int, int]:
    parts = version.split(".")
    return int(parts[0]), int(parts[1])


def test_poetry_pin_satisfies_the_lockfile():
    """`poetry.lock` records `lock-version = "2.1"`, which only Poetry >= 2.1 can
    read. Pinning below it would install a Poetry that refuses the repo's own
    lock — the seat would then disagree with the runner about the dependency
    graph, which is the class of defect TOOL-131 exists to remove."""
    lock = (REPO / "poetry.lock").read_text(encoding="utf-8")
    lock_version = re.search(r'^lock-version = "([\d.]+)"$', lock, re.MULTILINE)
    assert lock_version, "poetry.lock declares no lock-version"

    pinned = _pin("POETRY_VERSION")
    assert _major_minor(pinned) >= _major_minor(lock_version.group(1)), (
        f"bootstrap-controller.sh pins Poetry {pinned}, but poetry.lock needs "
        f">= {lock_version.group(1)}"
    )


def test_python_floor_matches_pyproject():
    """The script carries `PYTHON_MIN` as a copy of `python = "^3.12"` because it
    runs before anything can parse pyproject. The copy is only defensible if
    something fails when the two disagree — this is that something."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^python = "\^([\d.]+)"$', pyproject, re.MULTILINE)
    assert declared, "pyproject.toml declares no python constraint"

    assert _pin("PYTHON_MIN") == declared.group(1), (
        f"bootstrap-controller.sh requires Python {_pin('PYTHON_MIN')}, but "
        f"pyproject.toml requires ^{declared.group(1)}"
    )


def test_the_script_fails_fast():
    """`set -euo pipefail` is what makes a failed `apt-get` stop the script
    instead of letting it report success and hand off to a broken `make`."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"^set -euo pipefail$", text, re.MULTILINE)


def test_the_script_has_no_carriage_returns():
    """A `.sh` authored on Windows arrives with CRLF, and `.gitattributes` only
    normalises it on the way into git — the working-tree copy stays broken. bash
    then reads `set -euo pipefail\\r` as `set: pipefail` followed by
    `$'\\r': command not found`, so the script dies on line 15 before any check.

    Asserted on the bytes, not through `read_text`, because universal newlines
    silently translate the CR away and the failure disappears from the test.
    """
    assert b"\r" not in SCRIPT.read_bytes(), "scripts/bootstrap-controller.sh has CRLF line endings"


def test_the_runbook_points_at_the_script():
    """A manual recipe in the runbook and a script in `scripts/` are two sources
    of truth for the same install. The runbook must send the operator to the
    script, and the script is where the steps change."""
    assert "scripts/bootstrap-controller.sh" in RUNBOOK.read_text(encoding="utf-8")


_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="the script is bash")
# These two assert behaviour of a POSIX host: on Windows the script refuses at
# the uname guard before reaching either path, which is its own test below.
_posix = pytest.mark.skipif(
    sys.platform == "win32", reason="asserts the POSIX path; Windows stops at the uname guard"
)


def _run(*args: str, path_prefix: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = None
    if path_prefix is not None:
        env = dict(os.environ)
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
    # Relative path with cwd set to the repo: the `bash` on PATH may be WSL's,
    # which does not translate a Windows path and silently strips its
    # backslashes into a name that does not exist.
    return subprocess.run(  # noqa: S603 - fixed argv, repo-local script
        ["bash", "scripts/bootstrap-controller.sh", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


@_needs_bash
def test_help_exits_zero():
    result = _run("--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout


@_needs_bash
def test_an_unknown_argument_is_rejected():
    result = _run("--force")
    assert result.returncode == 2
    assert "unknown argument" in result.stderr


@_needs_bash
@_posix
def test_check_mode_reports_and_installs_nothing():
    """The runbook's first step is `--check`, so the mode has to be a real dry
    run. It is asserted by its own marker and by the absence of any install
    line, not by the exit status: that status legitimately differs between a
    machine that can be a controller and one that cannot."""
    result = _run("--check")
    combined = result.stdout + result.stderr
    assert "--check: not running 'make setup-ansible'" in combined
    assert "installing " not in combined
    assert result.returncode in (0, 1)


@_needs_bash
@_posix
def test_a_windows_shell_is_refused_before_anything_runs(tmp_path: Path):
    """The msi's Git Bash reaches ansible-core's `os.get_blocking()` and gets
    OSError [WinError 87]. The guard names that instead of letting it surface as
    a broken install, so it must run before the first check and before any
    `apt-get` — a refusal that installs first is not a refusal."""
    stub = tmp_path / "bin"
    stub.mkdir()
    uname = stub / "uname"
    uname.write_text("#!/bin/sh\necho MINGW64_NT-10.0\n", encoding="utf-8")
    uname.chmod(0o755)

    result = _run("--check", path_prefix=stub)
    assert result.returncode == 1
    assert "no Windows controller" in result.stderr
    assert "python3" not in result.stdout
