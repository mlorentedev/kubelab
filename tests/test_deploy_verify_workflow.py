"""`deploy-verify.yml` turns Argo CD's commit status into a red run (GITOPS-003 AC2, #1478).

The workflow runs only on master (a `status` event, a schedule, a dispatch), so
CI cannot exercise it on the branch that changes it. These tests pin its shape
and EXECUTE the status step's shell, so the verdict per state is measured rather
than read.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

from toolkit.features import delivery_health

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/deploy-verify.yml"
RUNBOOK = REPO_ROOT / "docs/runbooks/gitops-delivery-promotion.md"
PROPOSAL = REPO_ROOT / "specs/GITOPS-003/proposal.md"


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _step(job: dict, name: str) -> dict:
    return next(s for s in job["steps"] if s.get("name") == name)


def test_never_triggered_by_push(wf: dict) -> None:
    # A merge made with GITHUB_TOKEN (the unattended staging deploys, #1619)
    # starts no push workflow, so a push trigger would never run in the one case
    # this check compensates for.
    declared = delivery_health.triggers(wf)
    assert "push" not in declared
    assert {"status", "schedule", "workflow_dispatch"} <= declared


def test_the_status_job_judges_only_argo_contexts_and_the_commit_the_status_is_about(wf: dict) -> None:
    job = wf["jobs"]["on-status"]
    # Exact, not a substring: the job-level filter cannot be executed here, so
    # any edit to it must fail this test and be re-read.
    assert job["if"] == "github.event_name == 'status' && startsWith(github.event.context, 'argocd/kubelab-')
    step_env = _step(job, "Read the status Argo CD posted")["env"]
    # For a status event github.sha is the default branch tip, not the commit.
    assert step_env["SHA"] == "${{ github.event.sha }}"


def test_event_values_reach_the_shell_only_through_env(wf: dict) -> None:
    for job in wf["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run", "")
            assert "${{" not in run, f"{step.get('name')}: inline expression in run:"


def test_the_sweep_checks_prod_only(wf: dict) -> None:
    # Staging is on-demand (ace1) and can be repointed at a branch: neither
    # posts a status, and a runner cannot tell that from a sync that never ran.
    assert wf["jobs"]["sweep"]["strategy"]["matrix"]["env"] == ["prod"]


def test_the_sweep_budget_is_the_measured_n(wf: dict) -> None:
    minutes = int(re.search(r"\*\*N = (\d+) minutes\*\*", PROPOSAL.read_text()).group(1))
    step_env = _step(wf["jobs"]["sweep"], "Wait for master HEAD's status")["env"]
    assert int(step_env["MIN_AGE_SECONDS"]) == minutes * 60


def test_failure_messages_link_a_runbook_section_that_exists(wf: dict) -> None:
    anchor = wf["env"]["RUNBOOK"].split("#", 1)[1]
    assert wf["env"]["RUNBOOK"].split("/blob/master/", 1)[1].split("#")[0] == str(RUNBOOK.relative_to(REPO_ROOT))
    titles = re.findall(r"^## (.+)$", RUNBOOK.read_text(), re.M)
    headings = [re.sub(r"[^a-z0-9 -]", "", t.lower()).replace(" ", "-") for t in titles]
    assert anchor in headings


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.parametrize(
    ("state", "red"),
    [("success", False), ("pending", False), ("failure", True), ("error", True)],
)
def test_the_status_step_is_red_only_on_failure_or_error(wf: dict, state: str, red: bool) -> None:
    step = _step(wf["jobs"]["on-status"], "Read the status Argo CD posted")
    env = {
        **os.environ,
        "STATE": state,
        "CONTEXT": "argocd/kubelab-staging",
        "SHA": "1489265" + "0" * 33,
        "DESCRIPTION": "one or more synchronization tasks are not valid",
        "RUNBOOK": "https://example.invalid/runbook",
    }
    done = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True)
    assert (done.returncode != 0) is red, done.stdout + done.stderr
    if red:
        assert "one or more synchronization tasks are not valid" in done.stdout
        assert "https://example.invalid/runbook" in done.stdout
