"""`make worktree-init` must recover a checkout whose local lock went stale.

A checkout's lock can trail pyproject.toml: until TOOL-125 committed it,
`poetry.lock` was gitignored and each checkout kept the lock of the day it was
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
import os
import pathlib
import stat
import subprocess
import venv
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
    # A real install leaves the toolkit entry point where the recipe then checks for it.
    built = '[ -z "$WORKTREE_VENV" ] || { mkdir -p "$WORKTREE_VENV/bin"; : > "$WORKTREE_VENV/bin/toolkit"; chmod +x "$WORKTREE_VENV/bin/toolkit"; }; '
    install = f"{built}exit 0" if install_rc == 0 else f"exit {install_rc}"
    script.write_text(
        f'#!/bin/sh\necho "$*" >> "{log}"\n'
        f'case "$*" in "check --lock"*) exit {check_rc};; "env info"*) {where};; "install"*) {install};; esac\n'
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
        ["make", "--no-print-directory", "worktree-init", f"POETRY={script}", f"WORKTREE_VENV={tmp_path / '.venv'}"],
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


def test_the_venv_is_installed_in_the_worktree(tmp_path: pathlib.Path) -> None:
    """Ansible's record tasks run `<repo>/.venv/bin/toolkit`, so the venv must be there.

    Poetry's own default puts it in its cache unless a `.venv` already exists, and a
    worktree initialised that way failed a token record after the mint (#2902).
    """
    log = tmp_path / "env.log"
    fake = tmp_path / "poetry"
    fake.write_text(
        f'#!/bin/sh\ncase "$*" in "install"*) echo "$POETRY_VIRTUALENVS_IN_PROJECT:$VIRTUAL_ENV" >> "{log}"; '
        'mkdir -p "$WORKTREE_VENV/bin"; : > "$WORKTREE_VENV/bin/toolkit"; chmod +x "$WORKTREE_VENV/bin/toolkit";; '
        '"env info"*) exit 1;; esac\nexit 0\n',
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    done = subprocess.run(
        ["make", "--no-print-directory", "worktree-init", f"POETRY={fake}", f"WORKTREE_VENV={tmp_path / '.venv'}"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        # An activated venv elsewhere would take the install regardless of the setting.
        env={**{k: v for k, v in os.environ.items() if k != "POETRY_VIRTUALENVS_IN_PROJECT"}, "VIRTUAL_ENV": "/elsewhere"},
    )
    assert done.returncode == 0, done.stderr
    assert log.read_text(encoding="utf-8").split() == ["true:"]


def test_an_install_that_leaves_no_toolkit_in_the_worktree_fails(tmp_path: pathlib.Path) -> None:
    """The steps infer where Poetry builds; only the result says where it did (#2913)."""
    fake = tmp_path / "poetry"
    fake.write_text('#!/bin/sh\ncase "$*" in "env info"*) exit 1;; esac\nexit 0\n', encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    done = subprocess.run(
        ["make", "--no-print-directory", "worktree-init", f"POETRY={fake}", f"WORKTREE_VENV={tmp_path / '.venv'}"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0
    assert "bin/toolkit" in done.stderr


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

    def test_a_real_venv_is_stale_exactly_after_its_directory_is_renamed(self, tmp_path: pathlib.Path) -> None:
        """The shebang format comes from `python -m venv`, not from this file's fixture."""
        before = tmp_path / "before"
        before.mkdir()
        venv.EnvBuilder(with_pip=True).create(before / ".venv")
        assert _detector().relocated_shebang(before / ".venv") is None
        after = tmp_path / "after"
        before.rename(after)
        found = _detector().relocated_shebang(after / ".venv")
        assert found is not None
        assert "before" in found

    def test_worktree_init_keeps_a_healthy_venv_when_the_detector_cannot_run(self, tmp_path: pathlib.Path) -> None:
        venv_dir = _venv(tmp_path, shebang_dir=tmp_path / "old-name" / ".venv")
        script = tmp_path / "python3"
        asked = tmp_path / "detector-asked"
        script.write_text(f'#!/bin/sh\necho "$*" >> "{asked}"\nexit 2\n', encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        fake, _ = _fake_poetry(tmp_path, lock_is_fresh=True, venv=venv_dir)
        done = subprocess.run(
            # Not venv_dir itself: path equality would keep it whatever the detector said.
            ["make", "--no-print-directory", "worktree-init", f"POETRY={fake}", f"WORKTREE_VENV={tmp_path / 'wt' / '.venv'}"],
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        )
        assert done.returncode == 0, done.stderr
        assert str(venv_dir) in asked.read_text(encoding="utf-8"), "the detector must actually have been asked"
        assert (venv_dir / "bin" / "pytest").exists(), "exit 2 is a failure to ask, not a verdict"

    def test_a_signal_during_the_install_restores_the_previous_venv(self, tmp_path: pathlib.Path) -> None:
        """An `else` branch is never reached by a shell that a signal killed."""
        venv_dir = _venv(tmp_path, shebang_dir=tmp_path / "old-name" / ".venv")
        fake = tmp_path / "poetry"
        fake.write_text(
            '#!/bin/sh\ncase "$*" in\n"check --lock"*) exit 0;;\n'
            f'"env info"*) echo "{venv_dir}"; exit 0;;\n'
            '"install"*) kill -TERM $PPID; sleep 2; exit 0;;\nesac\nexit 0\n',
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        done = subprocess.run(
            ["make", "--no-print-directory", "worktree-init", f"POETRY={fake}"],
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
        )
        assert done.returncode != 0
        assert (venv_dir / "bin" / "pytest").exists(), "an interrupted rebuild must not strand the worktree"
        assert not (tmp_path / ".venv.relocated").exists()

    def test_a_missing_venv_is_not_stale(self, tmp_path: pathlib.Path) -> None:
        assert _detector().relocated_shebang(tmp_path / "nothing") is None

    def test_worktree_init_rebuilds_a_renamed_venv(self, tmp_path: pathlib.Path) -> None:
        venv = _venv(tmp_path, shebang_dir=tmp_path / "old-name" / ".venv")
        calls, done = _run(tmp_path, lock_is_fresh=True, venv=venv)
        assert done.returncode == 0, done.stderr
        assert calls == ["check", "install"]
        assert not (venv / "bin" / "pytest").exists(), "the stale venv must be set aside so poetry builds a fresh one"
        assert (venv / "bin" / "toolkit").exists()
        assert not (tmp_path / ".venv.relocated").exists(), "a successful rebuild discards the old copy"

    def test_a_cache_venv_is_replaced_by_one_in_the_worktree(self, tmp_path: pathlib.Path) -> None:
        """Poetry reuses a cache venv it already has, whatever POETRY_VIRTUALENVS_IN_PROJECT says.

        The setting governs only creation, so the env-var test above could not see this
        half: a worktree with a cache venv kept it and had no `.venv/bin/toolkit`.
        """
        cache = tmp_path / "cache" / "toolkit-AbC123-py3.13"
        cached = _venv(cache.parent / "x", shebang_dir=cache)
        cached.rename(cache)
        calls, done = _run(tmp_path, lock_is_fresh=True, venv=cache)
        assert done.returncode == 0, done.stderr
        assert calls == ["check", "install"]
        assert not cache.exists(), "a venv outside the worktree must be set aside so poetry builds .venv"
        assert (tmp_path / ".venv" / "bin" / "toolkit").exists(), "the rebuilt venv must be the worktree's"
        assert not (cache.parent / f"{cache.name}.relocated").exists(), "a successful rebuild discards the old copy"

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
