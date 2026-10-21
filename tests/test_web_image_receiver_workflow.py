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
stubbed. The step ran only on `repository_dispatch` from another repository, so
CI could not exercise it on the branch that changes it — "CI green" was not the
claim anyone needed. Since IDP-042 PR 7 it receives no dispatch at all; the file
stays until PR 8 deletes the workflow.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

from toolkit.features import promotion

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RECEIVER = REPO_ROOT / ".github/workflows/web-image-receiver.yml"

BRANCH = "deploy/staging-web"
TAG_ONE = "sha-aaa1111"
TAG_TWO = "sha-bbb2222"
OPEN_PR = "4242"

_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="the step is a bash script")


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
    return "\n".join(line for line in _step()["run"].splitlines() if not line.strip().startswith("#"))


# --- the cutover (IDP-042 PR 7) ------------------------------------------------


def test_the_dispatch_no_longer_reaches_this_workflow() -> None:
    """web is `receiver: generic`; two receivers on one event would race `deploy/staging-web`.

    `workflow_dispatch` stays only so the file is a valid workflow until PR 8 deletes it.
    It carries no tag, so the guard below refuses a manual run before the promotion.
    """
    workflow = yaml.safe_load(RECEIVER.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}, triggers


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


# --- The tag check (#1658) ------------------------------------------------------
#
# The promote step refused only tags not starting with `sha-`, so `sha-` followed
# by anything reached `toolkit deployment promote` and then a git refname. These
# run the shipped check with `poetry` stubbed, so a refused tag is proven never
# to reach the promotion, and an accepted one proven to.

_POETRY_STUB = """#!/usr/bin/env bash
echo "$*" >> "$POETRY_CALLS"
"""


def _promote_step() -> dict:
    workflow = yaml.safe_load(RECEIVER.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["promote-web"]["steps"]
    return next(s for s in steps if s.get("name") == "Promote web to staging")


def _run_promote_check(tmp_path: pathlib.Path, tag: str) -> tuple[int, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "poetry"
    stub.write_text(_POETRY_STUB, encoding="utf-8")
    stub.chmod(0o755)
    calls = tmp_path / "poetry-calls"
    calls.write_text("", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "TAG": tag, "POETRY_CALLS": str(calls)}
    proc = subprocess.run(["bash", "-e", "-c", _promote_step()["run"]], env=env, capture_output=True, text=True)
    return proc.returncode, calls.read_text(encoding="utf-8")


@_needs_bash
@pytest.mark.parametrize("tag", [TAG_ONE, "sha-0123456789abcdef0123456789abcdef01234567"])
def test_a_sha_tag_reaches_the_promotion(tmp_path: pathlib.Path, tag: str) -> None:
    code, calls = _run_promote_check(tmp_path, tag)
    assert code == 0
    assert f"--version {tag}" in calls


@_needs_bash
@pytest.mark.parametrize(
    "tag",
    ["sha-", "sha-abc12", "sha-../x", "sha-ABCDEF1", "sha-aaa1111\nsha-bbb2222", "sha-aaa1111 x", "v1.2.3", "dev"],
    ids=["empty", "short", "path", "uppercase", "newline", "space", "semver", "alias"],
)
def test_any_other_tag_is_refused_before_the_promotion(tmp_path: pathlib.Path, tag: str) -> None:
    code, calls = _run_promote_check(tmp_path, tag)
    assert code == 1
    assert calls == "", "a refused tag must never reach `toolkit deployment promote`"


def test_the_guard_reads_the_tag_the_dispatch_carried() -> None:
    """The tests above set TAG themselves; this pins where the workflow takes it from."""
    assert _promote_step()["env"]["TAG"] == "${{ github.event.client_payload.tag }}"


def test_the_guard_is_the_shape_the_promotion_accepts() -> None:
    """One shape in two languages: a change to either side that the other lacks fails here."""
    guard = re.search(r"=~ (\S+) \]\]", _promote_step()["run"])
    assert guard, "the promotion step no longer checks the tag with [[ =~ ]]"
    assert guard.group(1) == promotion._SHA_TAG.pattern
