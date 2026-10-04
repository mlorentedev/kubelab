"""`make worktree-init` must recover a checkout whose local lock went stale.

`poetry.lock` is gitignored, so each checkout keeps the lock of the day it was
first installed. When pyproject.toml gains a dependency, `poetry install`
refuses that lock ("pyproject.toml changed significantly since poetry.lock was
last generated") and the checkout cannot import what master now needs. Measured
2026-09-27: after #1870 added `jmespath`, the main checkout's
`tests/test_access_review.py` failed to collect and `worktree-init` exited 1.

The recipe runs against a fake `poetry` that records its calls, so the test
needs no network and no resolver.
"""

from __future__ import annotations

import pathlib
import stat
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent


def _fake_poetry(tmp_path: pathlib.Path, *, lock_is_fresh: bool) -> tuple[pathlib.Path, pathlib.Path]:
    log = tmp_path / "calls.log"
    script = tmp_path / "poetry"
    check_rc = 0 if lock_is_fresh else 1
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{log}"\n'
        f'case "$*" in "check --lock"*) exit {check_rc};; esac\n'
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


def _run(tmp_path: pathlib.Path, *, lock_is_fresh: bool) -> list[str]:
    script, log = _fake_poetry(tmp_path, lock_is_fresh=lock_is_fresh)
    subprocess.run(
        ["make", "--no-print-directory", "worktree-init", f"POETRY={script}"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.split()[0] for line in log.read_text(encoding="utf-8").splitlines()]


def test_a_stale_lock_is_regenerated_before_install(tmp_path: pathlib.Path) -> None:
    assert _run(tmp_path, lock_is_fresh=False) == ["check", "lock", "install"]


def test_a_fresh_lock_is_left_alone(tmp_path: pathlib.Path) -> None:
    assert _run(tmp_path, lock_is_fresh=True) == ["check", "install"]
