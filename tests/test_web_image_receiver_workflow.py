"""A staging promotion is either offered or rolled back — never left on a branch.

DELIVERY-006 (#1651). `web-image-receiver.yml` computes a staging promotion,
commits it, pushes the branch, and then opens the pull request that offers it.
Those are two operations against two different services with nothing joining
them, so a failure between them leaves the promotion committed on a branch
nobody was ever shown.

That is not hypothetical. It is the ONLY way this workflow has ever failed: 6 of
119 runs, 2026-06-28 through 2026-09-05, every one of them in this step and every
one on `GraphQL: API rate limit already exceeded`. The residue is measurable —
five `deploy/staging-web-*` branches existed when this was written and not one of
them had ever had a pull request, which is forced: the repo sets
`delete_branch_on_merge`, and the coalescing loop closes superseded PRs with
`--delete-branch`, so a surviving branch means the PR was never created.

The tests below EXECUTE the shipped step against a real git remote with `gh`
stubbed, rather than reading it. Written after the same reasoning as
`test_pr_agent_workflow.py`'s executed half: this step runs only on
`repository_dispatch` from another repository, so CI cannot exercise it on the
branch that changes it, and "CI green" would not be the claim anyone needs here.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RECEIVER = REPO_ROOT / ".github/workflows/web-image-receiver.yml"

TAG = "sha-abc1234"
BRANCH = f"deploy/staging-web-{TAG}"

_needs_bash = pytest.mark.skipif(
    shutil.which("bash") is None, reason="the step is a bash script"
)


def _step() -> dict:
    """The step under test, found by a distinctive substring of its `name:`.

    Same convention as `test_pr_agent_workflow.py`: a rename must make these
    tests error, not silently skip the subject.
    """
    workflow = yaml.safe_load(RECEIVER.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["promote-web"]["steps"]
    return next(s for s in steps if "Open staging deploy PR" in s.get("name", ""))


# `gh` replaced entirely. It answers as the real command's `--jq`-filtered output
# would, and logs every invocation so the ROUTE taken is observable rather than
# merely declared.
#
# The `*) exit 1` default is load-bearing: `gh pr create` matches no arm, so
# reverting the create to the GraphQL subcommand fails these tests behaviourally
# and not only through the string assertion below.
_GH_STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_CALLS"
case "$*" in
  *"-X POST"*"/pulls"*)
      if [ -n "${STUB_CREATE_FAILS:-}" ]; then
        echo "GraphQL: API rate limit already exceeded for user ID 13562150." >&2
        exit 1
      fi
      printf '%s\\n' "https://github.com/mlorentedev/kubelab/pull/9999" ;;
  "pr list"*) printf '%s\\t%s\\n' "$STUB_STALE_PR" "deploy/staging-web-sha-0000000" ;;
  "pr close"*) ;;
  *) exit 1 ;;
esac
"""
# `pr list` answers with ONE stale staging PR rather than nothing. An empty
# answer made `test_a_failed_create_does_not_close_the_previous_staging_offer`
# vacuous — no `pr close` could occur under any code, so it passed against a
# step with the `exit 1` deliberately removed. Measured, not assumed: the
# mutation was applied and the test stayed green.
STALE_PR = "1234"

# Git must not read the developer's own config: a global `core.hooksPath`,
# `commit.gpgsign` or `user.signingkey` would fail the commit for reasons that
# have nothing to do with the step.
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
}

STAGED_PATHS = (
    "infra/config/values/staging.yaml",
    "infra/k8s/overlays/staging/kustomization.yaml",
)


def _git(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    import os

    return subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    )


def _clone_with_remote(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """A working checkout on `master` with a real bare `origin` behind it.

    Real git rather than a stub, because the property under test is what the
    REMOTE holds after the step fails. A stubbed `git push --delete` could only
    confirm the command was issued, which is the thing that already looked fine
    in every one of the six failed runs.
    """
    remote = tmp_path / "origin.git"
    subprocess.run(  # noqa: S603
        ["git", "init", "--bare", "-b", "master", str(remote)],
        check=True,
        capture_output=True,
    )

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "master")
    _git(work, "config", "user.name", "test")
    _git(work, "config", "user.email", "test@example.invalid")
    for rel in STAGED_PATHS:
        path = work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("web: sha-0000000\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "base")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-u", "origin", "master")
    return work, remote


def _promote(work: pathlib.Path) -> None:
    """Stand in for `toolkit deployment promote`: leave the overlay changed."""
    for rel in STAGED_PATHS:
        (work / rel).write_text(f"web: {TAG}\n", encoding="utf-8")


def _run_step(
    tmp_path: pathlib.Path, work: pathlib.Path, **scenario: str
) -> tuple[subprocess.CompletedProcess, list[str]]:
    import os

    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "gh"
    stub.write_text(_GH_STUB, encoding="utf-8")
    stub.chmod(0o755)

    calls = tmp_path / "gh_calls"
    calls.touch()

    env = {
        **os.environ,
        **_GIT_ENV,
        "PATH": os.pathsep.join([str(bindir), os.environ["PATH"]]),
        "GH_CALLS": str(calls),
        "GH_TOKEN": "stub",
        "GITHUB_REPOSITORY": "mlorentedev/kubelab",
        "TAG": TAG,
        "STUB_CREATE_FAILS": "",
        "STUB_STALE_PR": STALE_PR,
        **scenario,
    }
    # `bash -e`, because that is what GitHub Actions uses for `run:` (`bash -e
    # {0}`). Running without it would exercise a different program: the whole
    # reason the create is wrapped in `if !` is that errexit would otherwise end
    # the step before it could clean up.
    proc = subprocess.run(  # noqa: S603
        ["bash", "-e", "-c", _step()["run"]],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc, calls.read_text().splitlines()


def _remote_branches(remote: pathlib.Path) -> list[str]:
    out = subprocess.run(  # noqa: S603
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=remote,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.split()


# --- the offer is made over a route that survives the outage ----------------


def _executable_lines() -> str:
    """The step body with its comments removed.

    Asserting against the raw `run:` matched the word `gh pr create` inside the
    comment that explains why it is gone — a guard failing on its own rationale.
    Same filtering as `test_the_inert_upstream_setting_was_not_ported`.
    """
    return "\n".join(
        line for line in _step()["run"].splitlines() if not line.strip().startswith("#")
    )


def test_the_pull_request_is_not_opened_with_the_graphql_subcommand() -> None:
    """`gh pr create` is a GraphQL mutation, and the GraphQL budget is spent by
    every tool authenticating as this account — CI, laptop, agents. That shared
    exhaustion is the sole cause of all six failures this workflow has had, so
    the create must not go back through it."""
    assert "gh pr create" not in _executable_lines(), (
        "the staging PR is opened with `gh pr create` again. That is a GraphQL "
        "mutation on an account-wide budget, and it is the one call that has "
        "ever failed here — 6 of 119 runs, always with the same rate-limit line."
    )


@_needs_bash
def test_the_offer_is_opened_over_rest_and_the_branch_survives(
    tmp_path: pathlib.Path,
) -> None:
    """The ordinary path, asserted on the route actually taken at runtime."""
    work, remote = _clone_with_remote(tmp_path)
    _promote(work)
    proc, calls = _run_step(tmp_path, work)

    assert proc.returncode == 0, (
        f"the step exited {proc.returncode}\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    created = [c for c in calls if "/pulls" in c]
    assert created, f"no pull-request call was made at all: {calls!r}"
    assert "-X POST" in created[0], f"the create did not go over REST: {created[0]!r}"
    assert BRANCH in _remote_branches(remote), (
        "the branch is missing from the remote after a SUCCESSFUL create; the "
        "pull request would reference a head that no longer exists"
    )
    assert [c for c in calls if c.startswith(f"pr close {STALE_PR}")], (
        f"the stale staging PR #{STALE_PR} was left open. Coalescing must still "
        f"run once the offer exists — this change was only supposed to alter how "
        f"the offer is made: {calls!r}"
    )


# --- and rolled back when it cannot be made ---------------------------------


@_needs_bash
def test_a_failed_create_leaves_no_branch_behind(tmp_path: pathlib.Path) -> None:
    """The defect itself, reproduced and then required not to happen.

    Six runs ended exactly here, and each left the promotion committed on a
    branch with no pull request. Asserted against the remote's own ref list, not
    against the step having issued a delete.
    """
    work, remote = _clone_with_remote(tmp_path)
    _promote(work)
    proc, _ = _run_step(tmp_path, work, STUB_CREATE_FAILS="1")

    assert BRANCH not in _remote_branches(remote), (
        f"{BRANCH} is still on the remote after the create failed. That is the "
        f"orphan branch this ticket is about: a staging promotion that was "
        f"computed, committed and pushed, and then offered to nobody."
    )
    assert proc.returncode != 0, (
        "the step succeeded despite never opening the staging offer. Cleaning up "
        "is not the same as recovering — staging is still on the older image, and "
        "a green run says otherwise."
    )
    assert "::error::" in proc.stdout, "the failure must name itself in the log"


@_needs_bash
def test_a_failed_create_does_not_close_the_previous_staging_offer(
    tmp_path: pathlib.Path,
) -> None:
    """Coalescing must never run when there is no new offer to coalesce onto.

    It closes the older staging PRs on the premise that this one supersedes
    them. If it ran after a failed create, the burst would end with the previous
    offer closed and no replacement — strictly worse than the orphan branch,
    because staging would be left with nothing to merge at all.

    Unlike its neighbours this passes on the pre-fix step too, and deliberately:
    it guards a risk the FIX introduces rather than one it removes. Before, the
    create failing under `bash -e` ended the step outright. Now it is wrapped in
    `if !` so the branch can be cleaned up, which suspends errexit — and a later
    edit dropping the `exit 1` from that block would fall straight through into
    coalescing with no offer to coalesce onto.

    That is exactly the mutation this was checked against: `exit 1` deleted, test
    re-run, and it goes red. The first version of it did not — the `gh` stub
    answered `pr list` with nothing, so no `pr close` was reachable under any
    code at all and the assertion could only ever pass.
    """
    work, _ = _clone_with_remote(tmp_path)
    _promote(work)
    _, calls = _run_step(tmp_path, work, STUB_CREATE_FAILS="1")

    assert not [c for c in calls if c.startswith("pr close")], (
        f"a stale staging PR was closed although the new one was never opened: "
        f"{calls!r}"
    )


# --- and nothing happens at all when there is nothing to promote ------------


@_needs_bash
def test_an_unchanged_overlay_pushes_nothing_and_calls_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """A re-dispatch of an already-promoted tag returns before the branch exists.

    This is what makes the unconditional delete above safe: the create is only
    reached when this run has just created this branch.
    """
    work, remote = _clone_with_remote(tmp_path)
    proc, calls = _run_step(tmp_path, work)

    assert proc.returncode == 0, proc.stderr
    assert calls == [], f"the API was called for a no-op promotion: {calls!r}"
    assert _remote_branches(remote) == ["master"], (
        "a deploy branch was pushed for a promotion that changed nothing"
    )
