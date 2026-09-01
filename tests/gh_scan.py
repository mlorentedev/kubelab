"""Where a `gh` call in a workflow step stands with respect to the repository.

Shared by `tests/test_gh_repo_context.py` (which jobs must declare a repository)
and `tests/test_dependabot_declaration.py` (which commands may not appear in the
declaring job). Both ask the same question — "which `gh` invocations does this
job actually execute, and what context do they have?" — and two answers would
drift. The drift is not hypothetical: the first revision of that guard excused a
call on a sibling step's `--repo`, and the reviewer on #1496 caught it precisely
because the two questions had already been answered differently.

The rules, and why each is what it is:

* **Porcelain subcommands need a repository; `gh api` does not.** `gh api` is
  called with an endpoint path that names it. Every other form resolves the
  repository from a git remote or from `GH_REPO`, and never from
  `GITHUB_REPOSITORY`, so in a checkout-less job it dies with
  "fatal: not a git repository" before any HTTP request.
* **Context is per step, with one carry-over.** A step is excused by `GH_REPO` on
  the job, `GH_REPO` on its own step, or `--repo` on the line making the call.
  `actions/checkout` is positional: it excuses the steps at and after it,
  because that is when the workspace first contains a `.git`, and it excuses
  nothing before it.
* **A line whose first token is `#` is prose.** Counting it would aim the guard
  at comments. A `gh` mention *after* code on the same line is still counted:
  failing closed here costs one extra `GH_REPO:` line, while failing the other
  way costs a week of red Dependabot PRs — the trade this file exists to make.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: `gh` subcommands that resolve a repository from their surroundings.
PORCELAIN = (
    "pr",
    "issue",
    "issues",
    "label",
    "labels",
    "release",
    "releases",
    "repo",
    "project",
    "run",
    "runs",
    "workflow",
    "workflows",
)

_CALL = re.compile(r"(?:^|[\s;&|(`$])gh\s+(?:%s)\b" % "|".join(PORCELAIN))
_REPO_FLAG = re.compile(r"(?:^|\s)--repo(?:\s|=)")
_CHECKOUT = "actions/checkout"


@dataclass(frozen=True)
class GhCall:
    """One executed `gh` invocation that needs a repository to resolve."""

    step_index: int
    step_name: str
    line: str


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in (job.get("steps") or []) if isinstance(step, dict)]


def checkout_step_index(job: dict[str, Any]) -> int | None:
    """Index of the first `actions/checkout`, or None when the job has none."""
    for index, step in enumerate(_steps(job)):
        if _CHECKOUT in str(step.get("uses") or ""):
            return index
    return None


def job_calls(job: dict[str, Any]) -> list[GhCall]:
    """Every repository-context `gh` call the job executes, context ignored."""
    calls: list[GhCall] = []
    for index, step in enumerate(_steps(job)):
        for raw in str(step.get("run") or "").splitlines():
            if raw.lstrip().startswith("#"):
                continue
            if _CALL.search(raw):
                calls.append(
                    GhCall(step_index=index, step_name=str(step.get("name") or f"step {index}"), line=raw.strip())
                )
    return calls


def unexcused(job: dict[str, Any]) -> list[GhCall]:
    """The calls in this job that would die on repository resolution.

    Empty means every one of them has a context GitHub will honour — declared on
    the job, declared on its own step, passed on its own line, or reached after
    a checkout put a `.git` in the workspace.
    """
    job_env = job.get("env") or {}
    job_declares = isinstance(job_env, dict) and bool(job_env.get("GH_REPO"))
    checked_out_at = checkout_step_index(job)

    offenders: list[GhCall] = []
    for call in job_calls(job):
        if checked_out_at is not None and call.step_index >= checked_out_at:
            continue
        if job_declares:
            continue
        step = _steps(job)[call.step_index]
        step_env = step.get("env") or {}
        if isinstance(step_env, dict) and bool(step_env.get("GH_REPO")):
            continue
        if _REPO_FLAG.search(call.line):
            continue
        offenders.append(call)
    return offenders
