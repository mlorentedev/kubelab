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
than a memo, following `tests/test_ci_hints_do_not_assert_a_cause.py`. Measured on
the pre-fix tree: one violation, this job, and no false positives across the
six other jobs here that call `gh pr`.

`gh api` is exempt on purpose: its endpoint is a repository path, so it carries
its own context. The subcommands below do not, and silently fall back to git —
which is what makes them a trap in a job with no checkout, and why this
repository's remedy for the declaring job (lesson-002: PR-field writes go through
REST, never the porcelain) leaves it clean here without a `GH_REPO` to declare.
This guard exists so that the next porcelain step added to such a job is caught
in CI rather than on a Dependabot PR a week later.
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Iterator

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github/workflows"

#: Subcommands that resolve a repository from the surrounding context rather
#: than from an argument. Anything `gh api` reaches is exempt by construction.
_NEEDS_REPO = re.compile(r"^\s*gh\s+(pr|issue|issues|label|labels|release|releases|repo|project|run|workflow)\b")

_CHECKOUT = "actions/checkout"


def _jobs() -> Iterator[tuple[pathlib.Path, str, dict]]:
    """Yield (file, job name, job) for every parsed workflow job."""
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(workflow, dict):
            continue
        for job_name, job in (workflow.get("jobs") or {}).items():
            if isinstance(job, dict):
                yield path, job_name, job


def _repo_context_calls(job: dict) -> list[str]:
    """Commands in this job that need a repository, comments excluded.

    A `# gh pr edit …` in a shell comment is documentation, and counting it
    would aim this guard at prose instead of at executed steps.
    """
    calls: list[str] = []
    for step in job.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for line in str(step.get("run") or "").splitlines():
            match = _NEEDS_REPO.match(line)
            if match and not line.lstrip().startswith("#"):
                calls.append(line.strip())
    return calls


def test_the_scan_finds_workflow_jobs_with_run_steps():
    """Without this, a moved directory turns the assertion below into a pass."""
    scanned = sum(1 for _, _, job in _jobs() if _repo_context_calls(job))
    assert scanned >= 5, (
        f"only {scanned} jobs with repository-context gh calls under {WORKFLOWS}; "
        "the scan has drifted and the check below is asserting nothing"
    )


def test_a_job_without_a_checkout_that_calls_gh_declares_its_repository():
    """Either check the repository out, or tell `gh` what it is. Both are fine."""
    offenders: list[str] = []
    for path, job_name, job in _jobs():
        calls = _repo_context_calls(job)
        if not calls:
            continue
        steps = job.get("steps") or []
        has_checkout = any(_CHECKOUT in str(step.get("uses") or "") for step in steps if isinstance(step, dict))
        if has_checkout:
            continue

        envs = [job.get("env") or {}] + [step.get("env") or {} for step in steps if isinstance(step, dict)]
        declares_repo = any(isinstance(env, dict) and env.get("GH_REPO") for env in envs)
        runs = "\n".join(str(step.get("run") or "") for step in steps if isinstance(step, dict))
        passes_repo = re.search(r"\bgh\s+\S[^\n]*\s--repo\b", runs) is not None
        if not (declares_repo or passes_repo):
            offenders.append(f"{path.name}::{job_name}\n      " + "\n      ".join(calls))

    assert not offenders, (
        "these jobs call gh without a git remote and without GH_REPO:\n  "
        + "\n  ".join(offenders)
        + "\n\ngh resolves the repository from a git remote or GH_REPO, never "
        "from GITHUB_REPOSITORY, so each call above dies with 'fatal: not a git "
        "repository' before it reaches the API. Set GH_REPO at job level — per "
        "command is today's command only — or run actions/checkout."
    )
