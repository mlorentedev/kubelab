"""A `gh` call in a job with no checkout has no repository, and says so badly.

`gh` resolves the target repository from a git remote or from `GH_REPO`. It does
not read `GITHUB_REPOSITORY`. A job that never runs `actions/checkout` therefore
has neither, and every subcommand that needs a repository dies before it reaches
the API:

    failed to run git: fatal: not a git repository (or any of the parent
    directories): .git

Measured 2026-08-31 on #1486-#1490. `dependabot-declare-unreviewed.yml` is the
half of CI-GATE-015 that writes the `merged-unreviewed` escape label; its last
step is `gh pr edit "$PR_NUMBER" --add-label "$LABEL"`, so it has applied that
label zero times since it shipped on 2026-08-24 (`45e0c900`). The two `gh api`
calls above it kept working because their endpoint path names the repository,
which left the PR body carrying the rationale section while the label never
landed — and the attestation gate, which requires both halves of the escape,
reporting `not reviewed, and not declared as such` on every dependency bump.

The same defect shipped once before, in dotfiles, where the preflight that was
supposed to catch expired PATs was itself dead on arrival (`GH_REPO` is set there
now, with a comment naming the incident: dotfiles lesson-134, ADR-031). Two
repositories, two independent discoveries, one class — so this is a guard rather
than a memo, following `tests/test_ci_hints_do_not_assert_a_cause.py`.

## Why the granularity is per step, not per job

Raised on PR #1496 by the reviewer that is not the author: the first revision of
this guard concatenated every step's `run:` text before asking whether a
repository was declared, so `--repo` (or `GH_REPO`) sitting on one step excused a
bare porcelain call on a sibling step. That is the same failure the guard exists
to prevent — a control that reads as covering the class while the step that
actually needs it goes unguarded — and it is the failure mode `dotfiles
tests/dependabot-ci.bats` names explicitly ("scoped PER JOB, not per file, and
that distinction is the whole assertion"). The synthetic table below pins the
per-step semantics, because no workflow in this repository exhibits the pattern
and a scan alone could not tell the two revisions apart.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

from tests.gh_scan import checkout_step_index, job_calls, unexcused

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github/workflows"


def _jobs() -> "list[tuple[pathlib.Path, str, dict[str, Any]]]":
    found = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(workflow, dict):
            continue
        for job_name, job in (workflow.get("jobs") or {}).items():
            if isinstance(job, dict):
                found.append((path, job_name, job))
    return found


def _job(**env: Any) -> dict[str, Any]:
    return {"env": env.get("env"), "steps": env["steps"]}


def _run(script: str, **env: Any) -> dict[str, str]:
    step = {"name": "run", "run": script}
    if env:
        step["env"] = env
    return step


def test_the_scan_finds_workflow_jobs_with_repository_context_calls():
    """Without this, a moved directory or a loosened matcher turns the assertion
    below into a pass.

    Lowered from 5 to 4 by #1645, and the reason matters. Nothing drifted: the
    coalescing loop in `web-image-receiver.yml` was the fifth, and it was removed
    because a stable staging branch has nothing to supersede. Its replacement is
    `gh api`, whose endpoint names the repository and so cannot have the defect
    this module guards — the population shrank by getting safer.

    That is the honest decrement, and it is also the last one that should happen
    silently. A floor edited downwards whenever it fires stops asserting
    anything, so #1669 proposes replacing the count with a relation: every
    workflow whose text contains a porcelain call must be found by the scan, and
    at least one must exist. Until then, treat a failure here as a question —
    "did a call migrate, or did the scan go blind?" — and answer it before
    touching the number.
    """
    with_calls = [(path, name) for path, name, job in _jobs() if job_calls(job)]
    assert len(with_calls) >= 4, (
        f"only {len(with_calls)} jobs call a porcelain gh subcommand under {WORKFLOWS}; "
        "the scan has drifted and the check below is asserting nothing"
    )


def test_a_job_without_a_checkout_that_calls_gh_declares_its_repository():
    """Either check the repository out, declare GH_REPO, or pass --repo.

    Each is scoped to the step that makes the call: see the module docstring.
    """
    offenders = []
    for path, job_name, job in _jobs():
        for call in unexcused(job):
            offenders.append(f"{path.name}::{job_name}::{call.step_name}\n      {call.line}")

    assert not offenders, (
        "these gh calls have no repository to resolve — no checkout at or before "
        "their step, no GH_REPO in the job or their own step, no --repo on the "
        "line:\n  " + "\n  ".join(offenders) + "\n\ngh resolves the repository "
        "from a git remote or GH_REPO, never from GITHUB_REPOSITORY, so each one "
        "dies with 'fatal: not a git repository' before it reaches the API. Set "
        "GH_REPO on the job, or on the step, or use gh api, whose endpoint names "
        "the repository itself."
    )


# --- the per-step semantics, pinned on synthetic jobs ------------------------
# (name, job, expected offenders)

_TABLE: list[tuple[str, dict[str, Any], int]] = [
    (
        "bare porcelain call, no checkout, no context",
        _job(steps=[_run("gh pr edit 1 --add-label x")]),
        1,
    ),
    (
        "GH_REPO on the job excuses every step",
        _job(env={"GH_REPO": "o/r"}, steps=[_run("gh pr edit 1"), _run("gh issue close 2")]),
        0,
    ),
    (
        "GH_REPO on the calling step excuses that step",
        _job(steps=[_run("gh pr edit 1", GH_REPO="o/r")]),
        0,
    ),
    (
        "GH_REPO on a sibling step does not excuse this one",
        _job(steps=[_run("gh label list", GH_REPO="o/r"), _run("gh pr edit 1")]),
        1,
    ),
    (
        "--repo on the same line excuses the call",
        _job(steps=[_run("gh pr edit 1 --repo o/r --add-label x")]),
        0,
    ),
    (
        "--repo on a different line of the same step does not",
        _job(steps=[_run("gh pr view 1\ngh pr edit 2 --repo o/r")]),
        1,
    ),
    (
        "a checkout in an earlier step excuses later ones",
        _job(steps=[{"name": "checkout", "uses": "actions/checkout@v5"}, _run("gh pr edit 1")]),
        0,
    ),
    (
        "a checkout in a LATER step excuses nothing",
        _job(steps=[_run("gh pr edit 1"), {"name": "checkout", "uses": "actions/checkout@v5"}]),
        1,
    ),
    (
        "gh api carries its repository in the endpoint",
        _job(steps=[_run('gh api -X POST "repos/${GITHUB_REPOSITORY}/issues/1/labels" -F "labels[]=x"')]),
        0,
    ),
    (
        "a shell comment is not a call",
        _job(steps=[_run("# gh pr edit 1 is broken here, see lesson-002\ngh api user")]),
        0,
    ),
    (
        "a call that is not the first token on its line still counts",
        _job(steps=[_run("prepare && gh pr close 1 --delete-branch")]),
        1,
    ),
    (
        "a call inside a command substitution still counts",
        _job(steps=[_run('sha="$(gh pr view 1 --json headRefOid)"')]),
        1,
    ),
    (
        "two unguarded calls in one step are two offenders",
        _job(steps=[_run("gh pr edit 1\ngh issue close 2")]),
        2,
    ),
]


@pytest.mark.parametrize("name,job,expected", _TABLE, ids=[row[0] for row in _TABLE])
def test_the_scoped_gh_repository(name: str, job: dict[str, Any], expected: int) -> None:
    """The matcher counts what it claims to count, in both directions.

    Asserting the offender count — not only "zero for the clean cases" — is what
    keeps a loosened matcher from turning the safe cases into a green that means
    nothing.
    """
    offenders = unexcused(job)
    assert len(offenders) == expected, f"{name}: expected {expected}, got {[o.line for o in offenders]}"


def test_the_matcher_ignores_subcommands_that_need_no_repository() -> None:
    """`gh api`, `gh auth`, `gh gh-api` … are out of scope by design."""
    job = _job(steps=[_run("gh api user\ngh auth status\ngh browse")])
    assert unexcused(job) == []
    assert job_calls(job) == []


def test_a_checkout_step_is_found_by_its_action_name_regardless_of_pinning() -> None:
    job = _job(steps=[{"name": "co", "uses": "actions/checkout@b4deff5 # v5"}])
    assert checkout_step_index(job) == 0
    assert checkout_step_index(_job(steps=[_run("gh pr edit 1")])) is None
