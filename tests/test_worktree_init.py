"""`make worktree-init` must recover a checkout whose local lock went stale.

`poetry.lock` is gitignored, so each checkout keeps the lock of the day it was
first installed. When pyproject.toml gains a dependency, `poetry install`
refuses that lock ("pyproject.toml changed significantly since poetry.lock was
last generated") and the checkout cannot import what master now needs. Measured
2026-09-27: after #1870 added `jmespath`, the main checkout's
`tests/test_access_review.py` failed to collect and `worktree-init` exited 1.

The recipe runs against a fake `poetry` that records its calls, so the test
needs no network and no resolver.

It must also recover a checkout whose directory was renamed (TOOL-067, #1707):
an in-project venv writes its own absolute path into every script's shebang, so
after a rename `pytest` exists but its interpreter does not, and re-running the
target used to do nothing because the directory was present.
"""

from __future__ import annotations

import importlib.util
import pathlib
import stat
import subprocess
from types import ModuleType

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _detector() -> ModuleType:
    spec = importlib.util.spec_from_file_location("venv_relocated", REPO / "scripts" / "venv_relocated.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_poetry(
    tmp_path: pathlib.Path, *, lock_is_fresh: bool, venv: pathlib.Path | None = None, install_rc: int = 0
) -> tuple[pathlib.Path, pathlib.Path]:
    log = tmp_path / "calls.log"
    script = tmp_path / "poetry"
    check_rc = 0 if lock_is_fresh else 1
    where = f'echo "{venv}"; exit 0' if venv else "exit 1"
    script.write_text(
        f'#!/bin/sh\necho "$*" >> "{log}"\n'
        f'case "$*" in "check --lock"*) exit {check_rc};; "env info"*) {where};; "install"*) exit {install_rc};; esac\n'
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


def _run(
    tmp_path: pathlib.Path,
    *,
    lock_is_fresh: bool,
    venv: pathlib.Path | None = None,
    install_rc: int = 0,
) -> tuple[list[str], subprocess.CompletedProcess[str]]:
    script, log = _fake_poetry(tmp_path, lock_is_fresh=lock_is_fresh, venv=venv, install_rc=install_rc)
    done = subprocess.run(
        ["make", "--no-print-directory", "worktree-init", f"POETRY={script}"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    calls = [line.split()[0] for line in log.read_text(encoding="utf-8").splitlines() if not line.startswith("env ")]
    return calls, done


def _venv(root: pathlib.Path, *, shebang_dir: pathlib.Path) -> pathlib.Path:
    """A venv whose `pytest` script names an interpreter under `shebang_dir`."""
    venv = root / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "pytest").write_text(f"#!{shebang_dir}/bin/python\nprint('pytest')\n", encoding="utf-8")
    return venv


def test_a_stale_lock_is_regenerated_before_install(tmp_path: pathlib.Path) -> None:
    calls, done = _run(tmp_path, lock_is_fresh=False)
    assert done.returncode == 0
    assert calls == ["check", "lock", "install"]


def test_a_fresh_lock_is_left_alone(tmp_path: pathlib.Path) -> None:
    calls, done = _run(tmp_path, lock_is_fresh=True)
    assert done.returncode == 0
    assert calls == ["check", "install"]


class TestRelocatedVenv:
    def test_a_venv_with_its_own_shebangs_is_ready(self, tmp_path: pathlib.Path) -> None:
        venv = _venv(tmp_path, shebang_dir=tmp_path / ".venv")
        assert _detector().relocated_shebang(venv) is None

    def test_a_venv_whose_scripts_name_another_directory_is_stale(self, tmp_path: pathlib.Path) -> None:
        venv = _venv(tmp_path, shebang_dir=tmp_path / "old-name" / ".venv")
        found = _detector().relocated_shebang(venv)
        assert found is not None
        assert "pytest" in found
        assert "old-name" in found

    def test_system_interpreters_and_shell_scripts_are_not_judged(self, tmp_path: pathlib.Path) -> None:
        venv = _venv(tmp_path, shebang_dir=tmp_path / ".venv")
        (venv / "bin" / "activate-helper").write_text("#!/bin/sh\n", encoding="utf-8")
        (venv / "bin" / "tool").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        assert _detector().relocated_shebang(venv) is None

    def test_a_missing_venv_is_not_stale(self, tmp_path: pathlib.Path) -> None:
        assert _detector().relocated_shebang(tmp_path / "nothing") is None

    def test_worktree_init_rebuilds_a_renamed_venv(self, tmp_path: pathlib.Path) -> None:
        venv = _venv(tmp_path, shebang_dir=tmp_path / "old-name" / ".venv")
        calls, done = _run(tmp_path, lock_is_fresh=True, venv=venv)
        assert done.returncode == 0, done.stderr
        assert calls == ["check", "install"]
        assert not venv.exists(), "the stale venv must be set aside so poetry builds a fresh one"
        assert not (tmp_path / ".venv.relocated").exists(), "a successful rebuild discards the old copy"

    def test_worktree_init_leaves_a_healthy_venv_alone(self, tmp_path: pathlib.Path) -> None:
        venv = _venv(tmp_path, shebang_dir=tmp_path / ".venv")
        _, done = _run(tmp_path, lock_is_fresh=True, venv=venv)
        assert done.returncode == 0
        assert (venv / "bin" / "pytest").exists()

    @pytest.mark.parametrize("install_rc", [1, 2])
    def test_a_failed_install_restores_the_previous_venv(self, tmp_path: pathlib.Path, install_rc: int) -> None:
        venv = _venv(tmp_path, shebang_dir=tmp_path / "old-name" / ".venv")
        _, done = _run(tmp_path, lock_is_fresh=True, venv=venv, install_rc=install_rc)
        assert done.returncode != 0
        assert (venv / "bin" / "pytest").exists(), "a failed target must not leave the worktree without a venv"
        assert not (tmp_path / ".venv.relocated").exists()
