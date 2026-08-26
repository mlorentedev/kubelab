"""A CI hint may not name a cause it has not observed.

Two workflows carried a `Hint on failure` step guarded by a bare `failure()`.
That expression is true when **any** earlier step in the job failed, so the hint
fires for a checkout error, a dependency install, a runner problem — and then
prints a diagnosis of the one thing it was written for.

Measured 2026-08-26 on PR #1421. `poetry install` took a truncated download from
PyPI:

    IncompleteRead(7188772 bytes read, 3008073 more expected)
    ProtocolError('Connection broken: ...')
    ##[error]Process completed with exit code 1

The drift step never ran. The job nevertheless reported:

    ##[error]Generator output drifted from committed files. Locally run:
    ##[error]  make config-generate ENV=staging

Both statements are false and the instruction is wasted work: reproducing it
locally on the same merged tree gave `✓ No drift in staging generated configs`,
exit 0. The reader is sent to regenerate files that had not drifted, and the
real failure — a flake worth a re-run — is not mentioned at all.

This is the same family as the false greens catalogued in #1387: a control whose
output does not distinguish "the thing I check is broken" from "I could not
check". Here it runs in the other direction, asserting a specific defect where
none was observed, which is worse than silence because it is actionable.

The fix is mechanical: give the checking step an `id`, and condition the hint on
`steps.<id>.outcome == 'failure'`. This asserts nobody reintroduces the bare
form.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github/workflows"

#: `failure()` in any of its spellings. A hint may still use `always()` or an
#: unconditional `if`, which do not claim to know why the job failed.
_BARE_FAILURE = {"failure()", "${{ failure() }}", "${{failure()}}"}

#: A step whose name promises a diagnosis. Extend when a new one appears; the
#: point is the class, not this list.
_DIAGNOSING = ("hint", "why this failed", "how to fix")


def _steps():
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        try:
            workflow = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(workflow, dict):
            continue
        for job_name, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if isinstance(step, dict):
                    yield path, job_name, step


def test_the_scan_finds_workflows_with_steps():
    """Without this, a moved directory turns the assertion below into a pass."""
    found = list(_steps())
    assert len(found) > 20, (
        f"only {len(found)} workflow steps found under {WORKFLOWS}; the scan has "
        "drifted and the check below is asserting nothing"
    )


def test_no_diagnosing_step_fires_on_a_bare_failure():
    """A hint must be keyed to the outcome of the step it explains."""
    offenders = []
    for path, job_name, step in _steps():
        name = str(step.get("name") or "")
        if not any(word in name.lower() for word in _DIAGNOSING):
            continue
        if str(step.get("if") or "").strip() in _BARE_FAILURE:
            offenders.append(f"{path.name}::{job_name}::{name!r}")

    assert not offenders, (
        "these steps diagnose a specific cause but fire on any job failure:\n  "
        + "\n  ".join(offenders)
        + "\n\n`failure()` is true when any earlier step failed, including a "
        "dependency install or a runner flake, so the hint states a cause it "
        "never observed. Give the checking step an `id:` and use "
        "`if: steps.<id>.outcome == 'failure'`."
    )
