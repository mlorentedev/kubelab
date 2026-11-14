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

# One lane per in-tree app: each has its own job, its own built-result variable and its
# own stable branch. console's is held to api's by tests/test_console_delivery_lane.py.
APPS = ("api", "console")
_JOBS = {"api": "open-pr", "console": "open-pr-console"}

# `poetry run toolkit ...` replaced: `image-tag` answers the pin the scenario
# sets, `promote` is logged, and anything else fails so an unexpected call is
# visible rather than silently absorbed. An app with no pin is a failure unless the
# step asks for `--allow-unpinned`, as the real command is.
_POETRY_STUB = """#!/usr/bin/env bash
case "$*" in
  *"deployment registered --app $STUB_APP"*) printf '%s\\n' "${STUB_REGISTERED:-true}" ;;
  *"deployment image-tag --env staging --app $STUB_APP"*)
    if [ -z "$STUB_PIN" ] && [[ "$*" != *"--allow-unpinned"* ]]; then exit 1; fi
    printf '%s\\n' "$STUB_PIN" ;;
  *"deployment promote --env staging --app $STUB_APP --version "*) echo "$*" >> "$POETRY_CALLS" ;;
  *) exit 1 ;;
esac
"""

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
}


@pytest.fixture(params=APPS)
def app(request: pytest.FixtureRequest) -> str:
    return request.param


def _job(app: str) -> dict:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/staging-deploy.yml").read_text(encoding="utf-8"))
    return workflow["jobs"][_JOBS[app]]


def _step(app: str, step_id: str) -> dict:
    """Found by its `id:`; a rename errors instead of skipping."""
    return next(s for s in _job(app)["steps"] if s.get("id") == step_id)


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
    app: str,
    tmp_path: pathlib.Path,
    work: pathlib.Path,
    pin: str,
    built: str,
    app_built: str = "success",
    registered: str = "true",
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
        f"{app.upper()}_BUILT": app_built,
        "STUB_APP": app,
        "STUB_REGISTERED": registered,
    }
    # `bash -e`, the shell GitHub Actions uses for `run:`.
    proc = subprocess.run(  # noqa: S603
        ["bash", "-e", "-c", _step(app, "promote")["run"]],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return proc, calls.read_text(encoding="utf-8").splitlines()


def test_the_job_checks_out_master_with_its_history(app: str) -> None:
    checkout = next(s for s in _job(app)["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "master"
    assert checkout["with"]["fetch-depth"] == 0


@_needs_bash
def test_a_newer_build_is_promoted(app: str, tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]) -> None:
    work, shas = history
    proc, calls = _run(app, tmp_path, work, pin=_tag(shas[0]), built=shas[2])
    assert proc.returncode == 0, proc.stderr
    assert calls == [f"run toolkit deployment promote --env staging --app {app} --version {_tag(shas[2])}"]


@_needs_bash
def test_the_pinned_build_itself_goes_through(
    app: str, tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]
) -> None:
    """A commit is its own ancestor; promote then writes nothing and the next step says so."""
    work, shas = history
    proc, calls = _run(app, tmp_path, work, pin=_tag(shas[1]), built=shas[1])
    assert proc.returncode == 0, proc.stderr
    assert len(calls) == 1


@_needs_bash
def test_an_older_build_than_the_pin_is_not_promoted(
    app: str, tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]
) -> None:
    work, shas = history
    proc, calls = _run(app, tmp_path, work, pin=_tag(shas[2]), built=shas[0])
    assert proc.returncode == 0, proc.stderr
    assert calls == []
    assert "already pins" in proc.stdout


@_needs_bash
def test_a_pin_git_cannot_place_fails_the_job(
    app: str, tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]
) -> None:
    work, shas = history
    proc, calls = _run(app, tmp_path, work, pin="sha-0ddba11", built=shas[2])
    assert proc.returncode != 0
    assert calls == []
    assert "cannot place" in proc.stdout


def test_only_a_successful_build_reaches_the_job(app: str) -> None:
    """The gate that keeps an unbuilt app out is the job's `if:`. The step's own
    `<APP>_BUILT` check never sees anything but `success`, so running it with another
    value would measure a state CI cannot produce."""
    gate = " ".join(_job(app)["if"].split())
    assert f"needs.build-{app}.result == 'success'" in gate


@_needs_bash
def test_an_app_with_no_pin_yet_is_a_first_promotion(
    app: str, tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]
) -> None:
    """No earlier build can precede the first, so there is nothing to compare: it promotes.

    The stub fails an unpinned read that does not pass `--allow-unpinned`, as the real
    command does, so this fails if the step stops asking for it.
    """
    work, shas = history
    proc, calls = _run(app, tmp_path, work, pin="", built=shas[2])
    assert proc.returncode == 0, proc.stderr
    assert calls == [f"run toolkit deployment promote --env staging --app {app} --version {_tag(shas[2])}"]


@_needs_bash
def test_an_app_the_registry_does_not_carry_yet_is_a_green_notice(
    app: str, tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]
) -> None:
    """Between this lane landing and the PR that registers the app, a push under its path must not
    red master. The step stops green with a notice, promotes nothing, and the next step finds no
    change to open a PR for."""
    work, shas = history
    proc, calls = _run(app, tmp_path, work, pin="", built=shas[2], registered="false")
    assert proc.returncode == 0, proc.stderr
    assert calls == []
    assert f"::notice::{app} is not in infra/config/products.yaml yet" in proc.stdout


@_needs_bash
def test_a_registered_app_still_promotes_when_the_registry_says_so(
    app: str, tmp_path: pathlib.Path, history: tuple[pathlib.Path, list[str]]
) -> None:
    """The other side: registering the app is all it takes, with nothing else touched."""
    work, shas = history
    proc, calls = _run(app, tmp_path, work, pin="", built=shas[2], registered="true")
    assert proc.returncode == 0, proc.stderr
    assert calls == [f"run toolkit deployment promote --env staging --app {app} --version {_tag(shas[2])}"]
