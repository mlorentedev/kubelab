"""A Renovate image bump regenerates what is derived from it — #3021.

The workflow holds a PAT and pushes to a branch, so its scope is what these tests
fix: which branches, which paths, and that the token never reaches a step running
code from the pushed branch.
"""

from __future__ import annotations

import json
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/renovate-derived.yml"
CHECK_DRIFT = REPO / ".github/workflows/check-config-drift.yml"
RENOVATE = REPO / "renovate.json"
BOT_EMAIL = "bot@kubelab.live"
DERIVED = {"infra/k8s/base/kustomization.yaml", "infra/config/platform.json"}


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["regenerate"]["steps"]


def test_it_runs_only_on_a_push_to_a_renovate_branch() -> None:
    # PyYAML reads the bare `on` key as True.
    assert _workflow()[True] == {"push": {"branches": ["renovate/**"]}}


def test_the_token_is_only_in_the_step_that_pushes() -> None:
    holders = [step for step in _steps() if "RELEASE_PLEASE_TOKEN" in json.dumps(step)]
    assert len(holders) == 1
    assert "git push" in holders[0]["run"]
    assert "toolkit" not in holders[0]["run"], "the pushed branch's code must not run beside the token"


def test_checkout_leaves_no_credential_for_the_toolkit() -> None:
    checkout = next(step for step in _steps() if "actions/checkout" in step.get("uses", ""))
    assert checkout["with"]["persist-credentials"] is False


def test_only_the_derived_files_are_staged() -> None:
    push_step = next(step for step in _steps() if "git push" in step.get("run", ""))
    added = re.findall(r"^\s*git add (.+)$", push_step["run"], flags=re.M)
    assert len(added) == 1
    assert set(added[0].split()) == DERIVED


def test_it_regenerates_what_the_drift_gate_checks() -> None:
    regenerate = next(step for step in _steps() if step.get("name") == "Regenerate")["run"]
    assert "toolkit sync images" in regenerate
    assert "toolkit sync platform-json" in regenerate
    assert "toolkit sync images --check" in CHECK_DRIFT.read_text(encoding="utf-8")


def test_renovate_does_not_read_the_commit_as_a_human_edit() -> None:
    """Without this Renovate stops rebasing the branch after the first sync commit."""
    assert BOT_EMAIL in WORKFLOW.read_text(encoding="utf-8")
    assert BOT_EMAIL in json.loads(RENOVATE.read_text(encoding="utf-8"))["gitIgnoredAuthors"]
