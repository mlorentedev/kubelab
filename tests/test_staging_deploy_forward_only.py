"""api's staging deploy PR is written on master's tip and only ever moves forward.

#3122. `staging-deploy.yml`'s `open-pr` job checked out the PUSHED sha, which is
minutes old by the time the build ends. #3120 merged a bump of the same line in
that window, so the PR the job wrote conflicted with master, and a re-run would
have written the same conflict. The job now checks out master's tip.

That checkout opens a second hole, and closing it is the reason this file exists:
on master's tip the pin may already be NEWER than the build. The concurrency
group orders jobs by when their build finished, not by push order. Promoting
there would write a clean, conflict-free downgrade, and deploy-merge merges a
clean version move without a human (DELIVERY-004). So the promote step asks git
whether the current pin is an ancestor of the pushed commit, and promotes only
when it is.

These tests EXECUTE the shipped step against a real git history, with `poetry`
stubbed. The step runs only on a push to master, so CI cannot exercise it on the
branch that changes it.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="the step is a bash script")

# `poetry run toolkit ...` replaced: `image-tag` answers the pin the scenario
# sets, `promote` is logged, and anything else fails so an unexpected call is
# visible rather than silently absorbed.
_POETRY_STUB = """#!/usr/bin/env bash
case "$*" in
  *"deployment image-tag --env staging --app api"*) printf '%s\\n' "$STUB_PIN" ;;
  *"deployment promote --env staging --app api --version "*) echo "$*" >> "$POETRY_CALLS" ;;
  *) exit 1 ;;
esac
"""

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
}


def _job() -> dict:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/staging-deploy.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]["open-pr"]


def _step(step_id: str) -> dict:
    """Found by its `id:`; a rename errors instead of skipping."""
    return next(s for s in _job()["steps"] if s.get("id") == step_id)


def _git(cwd: pathlib.Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **_GIT_ENV},
    ).stdout.strip()


@pytest.fixture
def history(tmp_path: pathlib.Path) -> tuple[pathlib.Path, list[str]]:
    """A checkout whose master is three commits, oldest first."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "master")
    _git(work, "config", "user.name", "test")
    _git(work, "config", "user.email", "test@example.invalid")
    shas = []
    for n in range(3):
        (work / "f").write_text(f"{n}\n", encoding="utf-8")
        _git(work, "add", "f")
        _git(work, "commit", "-m", f"c{n}")
        shas.append(_git(work, "rev-parse", "HEAD"))
    return work, shas


def _tag(sha: str) -> str:
    return f"sha-{sha[:7]}"


def _run(
    tmp_path: pathlib.Path, work: pathlib.Path, pin: str, built: str, api_built: str = "success"
) -> tuple[subprocess.CompletedProcess, list[str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "poetry"
    stub.write_text(_POETRY_STUB, encoding="utf-8")
    stub.chmod(0o755)
    calls = tmp_path / "poetry_calls"
    calls.touch()

    env = {
        **os.environ,
        **_GIT_ENV,
        "PATH": os.pathsep.join([str(bindir), os.environ["PATH"]]),
        "POETRY_CALLS": str(calls),
        "STUB_PIN": pin,
        "GITHUB_SHA": built,
        "SHA": _tag(built),
        "API_BUILT": api_built,
    }
    # `bash -e`, the shell GitHub Actions uses for `run:`.
    proc = subprocess.run(  # noqa: S603
        ["bash", "-e", "-c", _step("promote")["run"]],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return proc, calls.read_text(encoding="utf-8").splitlines()


def test_the_job_checks_out_master_with_its_history() -> None:
    checkout = next(s for s in _job()["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "master"
    assert checkout["with"]["fetch-depth"] == 0


@_needs_bash
def test_a_newer_build_is_promoted(tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]) -> None:
    work, shas = history
    proc, calls = _run(tmp_path, work, pin=_tag(shas[0]), built=shas[2])
    assert proc.returncode == 0, proc.stderr
    assert calls == [f"run toolkit deployment promote --env staging --app api --version {_tag(shas[2])}"]


@_needs_bash
def test_the_pinned_build_itself_goes_through(tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]) -> None:
    """A commit is its own ancestor; promote then writes nothing and the next step says so."""
    work, shas = history
    proc, calls = _run(tmp_path, work, pin=_tag(shas[1]), built=shas[1])
    assert proc.returncode == 0, proc.stderr
    assert len(calls) == 1


@_needs_bash
def test_an_older_build_than_the_pin_is_not_promoted(
    tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]
) -> None:
    work, shas = history
    proc, calls = _run(tmp_path, work, pin=_tag(shas[2]), built=shas[0])
    assert proc.returncode == 0, proc.stderr
    assert calls == []
    assert "already pins" in proc.stdout


@_needs_bash
def test_a_pin_git_cannot_place_fails_the_job(tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]) -> None:
    work, shas = history
    proc, calls = _run(tmp_path, work, pin="sha-0ddba11", built=shas[2])
    assert proc.returncode != 0
    assert calls == []
    assert "cannot place" in proc.stdout


@_needs_bash
def test_an_unbuilt_app_is_not_promoted(tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]) -> None:
    work, shas = history
    proc, calls = _run(tmp_path, work, pin=_tag(shas[0]), built=shas[2], api_built="skipped")
    assert proc.returncode == 0, proc.stderr
    assert calls == []
