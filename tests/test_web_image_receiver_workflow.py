"""One long-lived staging offer, force-updated — never a queue of pull requests.

DELIVERY-005 (#1645). `web-image-receiver.yml` used to key its branch on the
promoted sha, so every web push minted a new branch and therefore a new pull
request. Measured over every `chore(staging): deploy` PR this repository has had:
104 opened, 35 merged, 68 closed — and 67 of those closes were superseded by a
newer PR rather than declined. The human gate was exercised as a genuine "hold
staging" exactly once.

The branch is now `deploy/staging-web`, stable, force-updated to the newest sha,
with its pull request created once and patched thereafter. The gate is untouched:
merging still moves staging, and declining is now simply not merging.

DELIVERY-006 (#1651) is retired by the same change rather than kept. Its defect
was a push that succeeded followed by a create that failed, leaving a branch
nobody was offered; on a stable branch the ref is *meant* to persist, so there is
nothing to roll back and no reconciliation to get wrong.

These tests EXECUTE the shipped step against a real bare git remote with `gh`
stubbed. The step runs only on `repository_dispatch` from another repository, so
CI cannot exercise it on the branch that changes it — "CI green" is not the claim
anyone needs here.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RECEIVER = REPO_ROOT / ".github/workflows/web-image-receiver.yml"

BRANCH = "deploy/staging-web"
TAG_ONE = "sha-aaa1111"
TAG_TWO = "sha-bbb2222"
OPEN_PR = "4242"

_needs_bash = pytest.mark.skipif(
    shutil.which("bash") is None, reason="the step is a bash script"
)


def _step() -> dict:
    """The step under test, found by a distinctive substring of its `name:`.

    A rename must make these tests error rather than silently skip their subject.
    """
    workflow = yaml.safe_load(RECEIVER.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["promote-web"]["steps"]
    return next(s for s in steps if "staging deploy PR" in s.get("name", ""))


def _executable_lines() -> str:
    """The step body without comments.

    Asserting against the raw `run:` matched `gh pr create` inside the comment
    explaining why it is gone — a guard failing on its own rationale.
    """
    return "\n".join(
        line for line in _step()["run"].splitlines() if not line.strip().startswith("#")
    )


# `gh` replaced entirely, logging every invocation so the ROUTE and the ORDER are
# observable rather than declared. The `*) exit 1` default is load-bearing: any
# `gh pr <subcommand>` matches no arm, so a revert to the GraphQL subcommands
# fails behaviourally and not only through the string assertions below.
_GH_STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_CALLS"
case "$*" in
  *"/pulls?state=open&head="*)
      if [ "${STUB_LOOKUP:-}" = "fail" ]; then
        echo "GraphQL: API rate limit already exceeded" >&2
        exit 1
      fi
      printf '%s\\n' "${STUB_OPEN_PR:-}" ;;
  *"-X PATCH"*"/pulls/"*)
      printf '%s\\n' "https://github.com/mlorentedev/kubelab/pull/${STUB_OPEN_PR}" ;;
  *"-X POST"*"/pulls"*)
      printf '%s\\n' "https://github.com/mlorentedev/kubelab/pull/9999" ;;
  *) exit 1 ;;
esac
"""

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

    Real git, because the properties under test are what the REMOTE holds and how
    many branches it grows. A stubbed `git push` could only confirm a command was
    issued, which is what already looked fine while 104 PRs piled up.
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


def _promote(work: pathlib.Path, tag: str) -> None:
    """Stand in for `toolkit deployment promote`: leave the overlay changed."""
    for rel in STAGED_PATHS:
        (work / rel).write_text(f"web: {tag}\n", encoding="utf-8")


def _run_step(
    tmp_path: pathlib.Path,
    work: pathlib.Path,
    tag: str = TAG_ONE,
    promote: bool = True,
    calls_path: pathlib.Path | None = None,
    **scenario: str,
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run one dispatch end to end, as CI performs it.

    Checkout, then promote, then the step — in that order, because that is the
    job. Resetting to `master` first is what makes a second call faithful: every
    dispatch gets a new `actions/checkout`, which lands on master and knows
    nothing of the deploy branch. That is also the condition that makes
    `--force-with-lease` unusable in this step.

    `promote=False` is the no-op dispatch: a checkout with nothing to stage.
    """
    bindir = tmp_path / "bin"
    if not bindir.exists():
        bindir.mkdir()
        stub = bindir / "gh"
        stub.write_text(_GH_STUB, encoding="utf-8")
        stub.chmod(0o755)

    calls = calls_path or (tmp_path / "gh_calls")
    calls.touch()

    _git(work, "checkout", "-f", "master")
    if promote:
        _promote(work, tag)

    env = {
        **os.environ,
        **_GIT_ENV,
        "PATH": os.pathsep.join([str(bindir), os.environ["PATH"]]),
        "GH_CALLS": str(calls),
        "GH_TOKEN": "stub",
        "GITHUB_REPOSITORY": "mlorentedev/kubelab",
        "TAG": tag,
        "STUB_OPEN_PR": "",
        "STUB_LOOKUP": "",
        **scenario,
    }
    # `bash -e`, because that is the shell GitHub Actions uses for `run:`
    # (`bash -e {0}`). Without it this would exercise a different program.
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
    return sorted(out.stdout.split())


def _remote_file(remote: pathlib.Path, ref: str, path: str) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", "show", f"{ref}:{path}"],
        cwd=remote,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout


# --- AC1: two pushes, one pull request --------------------------------------


@_needs_bash
def test_two_consecutive_dispatches_produce_one_pr_and_one_branch(
    tmp_path: pathlib.Path,
) -> None:
    """The whole ticket, executed.

    Before this change the second dispatch minted a second branch and a second
    pull request, and the first was closed as superseded. 67 of 68 closes were
    that. Now the second dispatch updates what the first opened.
    """
    work, remote = _clone_with_remote(tmp_path)
    calls = tmp_path / "gh_calls"

    first, _ = _run_step(tmp_path, work, tag=TAG_ONE, calls_path=calls)
    assert first.returncode == 0, first.stderr

    # The offer now exists, so the second dispatch's lookup finds it.
    second, all_calls = _run_step(
        tmp_path, work, tag=TAG_TWO, calls_path=calls, STUB_OPEN_PR=OPEN_PR
    )
    assert second.returncode == 0, second.stderr

    creates = [c for c in all_calls if "-X POST" in c and "/pulls" in c]
    updates = [c for c in all_calls if "-X PATCH" in c and "/pulls/" in c]
    assert len(creates) == 1, (
        f"two dispatches opened {len(creates)} pull requests. One stable branch "
        f"must carry one offer: {all_calls!r}"
    )
    assert len(updates) == 1, f"the second dispatch did not update the offer: {all_calls!r}"

    assert _remote_branches(remote) == [BRANCH, "master"], (
        "a second deploy branch was minted. The per-sha branch is exactly what "
        "produced 104 branches and 68 closes."
    )


# --- AC2: the offer describes the sha it is actually offering ---------------


@_needs_bash
def test_the_update_renames_the_pr_to_the_sha_it_now_offers(
    tmp_path: pathlib.Path,
) -> None:
    """A long-lived PR whose title names an older commit is worse than churn.

    Someone merges a pull request by reading its title. If the branch moves and
    the title does not, the title becomes an invitation to merge something else —
    the point-of-use staleness this repository has hit repeatedly.
    """
    work, remote = _clone_with_remote(tmp_path)
    calls = tmp_path / "gh_calls"

    _run_step(tmp_path, work, tag=TAG_ONE, calls_path=calls)
    _run_step(tmp_path, work, tag=TAG_TWO, calls_path=calls, STUB_OPEN_PR=OPEN_PR)

    patch = next(c for c in calls.read_text().splitlines() if "-X PATCH" in c)
    assert TAG_TWO in patch, f"the update did not carry the new sha: {patch!r}"
    assert TAG_ONE not in patch, f"the update still names the previous sha: {patch!r}"

    # And the branch really holds the newer promotion, not merely a new title.
    for rel in STAGED_PATHS:
        assert TAG_TWO in _remote_file(remote, BRANCH, rel), (
            f"{rel} on the remote branch does not hold {TAG_TWO}"
        )


# --- AC4: an unchanged overlay changes nothing -------------------------------


@_needs_bash
def test_an_unchanged_overlay_pushes_nothing_and_calls_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """Idempotence. A re-dispatch of an already-promoted tag must not push an
    empty commit, must not touch the pull request, and must not go red."""
    work, remote = _clone_with_remote(tmp_path)
    proc, calls = _run_step(tmp_path, work, promote=False)

    assert proc.returncode == 0, proc.stderr
    assert calls == [], f"the API was called for a no-op promotion: {calls!r}"
    assert _remote_branches(remote) == ["master"], "a deploy branch was pushed for nothing"


# --- AC5: closing means "not now", never "never again" ----------------------


@_needs_bash
def test_a_closed_offer_is_reopened_by_the_next_dispatch(
    tmp_path: pathlib.Path,
) -> None:
    """The capability ADR-037 protects, preserved on a stable branch.

    Declining used to mean closing a PR a newer one would replace anyway. Now it
    means not merging — and if someone closes the PR outright to hold staging, the
    next dispatch must offer again rather than leave the app with no live offer.
    The lookup asks for `state=open`, so a closed PR reads as absent.
    """
    work, remote = _clone_with_remote(tmp_path)
    calls = tmp_path / "gh_calls"

    _run_step(tmp_path, work, tag=TAG_ONE, calls_path=calls)

    # The human closes it. `state=open` now answers empty, as GitHub would.
    proc, all_calls = _run_step(
        tmp_path, work, tag=TAG_TWO, calls_path=calls, STUB_OPEN_PR=""
    )

    assert proc.returncode == 0, proc.stderr
    creates = [c for c in all_calls if "-X POST" in c and "/pulls" in c]
    assert len(creates) == 2, (
        f"a closed staging offer was not reopened: {all_calls!r}. Closing must "
        f"mean 'not now', never 'never again' — otherwise holding staging once "
        f"strands the app with no offer for good."
    )
    assert _remote_branches(remote) == [BRANCH, "master"]


# --- ordering: ask before you touch the remote -------------------------------


@_needs_bash
def test_an_unanswerable_lookup_leaves_the_remote_untouched(
    tmp_path: pathlib.Path,
) -> None:
    """The lookup runs BEFORE the push, and that ordering is the point.

    Pushing first and then failing to reach the API would leave the branch
    holding a new promotion while the pull request still advertised the old sha —
    exactly the stale-title failure AC2 forbids, arrived at by a different road.
    Asking first means an API failure costs nothing: the offer and its
    description still agree, and the next dispatch retries.
    """
    work, remote = _clone_with_remote(tmp_path)
    proc, calls = _run_step(tmp_path, work, STUB_LOOKUP="fail")

    assert proc.returncode != 0, "an unanswerable lookup must fail the run"
    assert _remote_branches(remote) == ["master"], (
        "the branch was pushed although the pull request could not be reached. "
        "The offer would then describe a sha it no longer carries."
    )
    assert not [c for c in calls if "-X POST" in c or "-X PATCH" in c], (
        f"a write was attempted after the lookup failed: {calls!r}"
    )


# --- what the change removes -------------------------------------------------


def test_the_coalescing_loop_is_gone_with_its_graphql_calls() -> None:
    """With one branch there is nothing to supersede.

    `gh pr list` and `gh pr close` were the last GraphQL calls in this step, kept
    deliberately in #1660 because a coalescing failure could not drop an offer.
    They have no subject any more, and a loop that closes `deploy/staging-web-*`
    PRs would now match the live offer itself.
    """
    body = _executable_lines()
    for gone in ("gh pr create", "gh pr list", "gh pr close"):
        assert gone not in body, (
            f"{gone!r} is back in the step. It is a GraphQL call, and with a "
            f"stable branch it also has nothing left to act on."
        )


def test_the_branch_is_keyed_on_the_app_and_not_on_the_tag() -> None:
    """The defect in one line: `deploy/staging-web-${TAG}` mints a branch per push.

    Asserted on the executable body rather than the whole `run:`, so the comment
    that explains the old shape does not satisfy the guard against it.
    """
    body = _executable_lines()
    assert f'BRANCH="{BRANCH}"' in body, "the staging branch is no longer the stable one"
    assert 'BRANCH="deploy/staging-web-${TAG}"' not in body, (
        "the branch is keyed on the tag again; every dispatch will mint a new "
        "branch and a new pull request, which is #1645"
    )
