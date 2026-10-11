"""The commit status must not claim a review that did not happen.

`review-attestation` classifies a PR into states that share an exit code:

    attested   a review happened                       -> 0
    disclosed  no review, but the escape is declared    -> 0

The workflow mapped BOTH to `description="a review happened"`. So a PR merged
under the documented unreviewed escape — label plus rationale, exactly as
CLAUDE.md prescribes — published a green commit status asserting it had been
reviewed.

Observed on #1256: PR-Agent published nothing twice, the escape was declared,
and the status read "a review happened".

That is the failure this gate exists to prevent, reproduced inside the gate.
TOOL-021 was filed because 35 of 40 merged PRs had no review behind a green
check; a status that says "reviewed" over a declared-unreviewed merge recreates
exactly that, and the status is the durable artefact — it is what branch
protection reads and what a human glances at months later.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/review-attestation.yml"
FEATURE = REPO / "toolkit/features/review_attestation.py"


@pytest.fixture(scope="module")
def publish_step() -> str:
    wf = yaml.safe_load(WORKFLOW.read_text())
    for job in wf["jobs"].values():
        for step in job.get("steps", []):
            if "commit status" in str(step.get("name", "")).lower():
                return step["run"]
    pytest.fail("no 'Publish the commit status' step found")


def test_a_declared_unreviewed_merge_does_not_claim_a_review(publish_step: str) -> None:
    """The whole point. Both states exit 0; only one of them was reviewed."""
    success_descriptions = re.findall(r'state="success";\s*description="([^"]+)"', publish_step)
    claiming = [d for d in success_descriptions if "a review happened" in d]
    assert len(success_descriptions) >= 2, (
        f"the success branch publishes a single description {success_descriptions}. "
        "`attested` and `disclosed` share an exit code and must not share wording: "
        "one was reviewed and the other explicitly was not."
    )
    assert len(claiming) <= 1, f"more than one success state claims a review: {success_descriptions}"


def test_the_disclosed_state_is_named_in_the_status(publish_step: str) -> None:
    """Named, so the reader learns which escape was taken rather than inferring
    it from a label they would have to go looking for."""
    assert "disclosed" in publish_step or "declared" in publish_step.lower(), (
        "nothing in the published status distinguishes a declared unreviewed merge"
    )


def test_both_zero_exit_states_still_exist_in_the_classifier() -> None:
    """Guard the guard: if the classifier stopped emitting `disclosed`, the
    wording split above would be defending a distinction that no longer exists.
    """
    src = FEATURE.read_text()
    assert '"attested"' in src and '"disclosed"' in src


def test_a_failure_still_reads_as_one(publish_step: str) -> None:
    """The other half: making the success branch honest must not soften the red."""
    assert re.search(r'state="failure";\s*description="not reviewed', publish_step)


# --------------------------------------------------------------------------- #
# The state the status is chosen from must be the classifier's, not a word
# scraped from its prose (#2208).
#
# The workflow took the LAST state word anywhere in the output. A disclosed PR
# on which a reviewer had posted a quota notice prints
# "disclosed — no review ran (coderabbitai declined), ...", so the last word was
# `declined`, the disclosed branch never matched, and the status fell through to
# "a review happened". Observed on #2206.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def classify_step() -> str:
    wf = yaml.safe_load(WORKFLOW.read_text())
    for job in wf["jobs"].values():
        for step in job.get("steps", []):
            if step.get("id") == "attest":
                return step["run"]
    pytest.fail("no step with id 'attest' found")


def test_the_state_is_read_from_a_file_the_classifier_writes(classify_step: str) -> None:
    assert "--state-file" in classify_step, (
        "the Classify step does not ask the classifier for its state; it can only "
        "infer it from the log, which quotes reviewer notices and PR values"
    )
    assignments = re.findall(r"^\s*state_word=(.*)$", classify_step, re.MULTILINE)
    assert assignments, "the Classify step no longer sets state_word"
    for rhs in assignments:
        assert "$state_file" in rhs and "$out" not in rhs, (
            f"state_word is derived from something other than the state file: {rhs!r}. "
            "Any pattern over the log reads whichever state word its prose quoted last."
        )
    assert not re.search(r"grep[^\n]*\b(attested|exempt|disclosed|declined|pending)\b", classify_step), (
        "the Classify step still greps state words out of the classifier's prose"
    )


def test_a_disclosed_pr_with_a_declined_notice_reports_disclosed(tmp_path: Path) -> None:
    """#2206's exact shape, through the CLI the workflow runs."""
    import json

    from typer.testing import CliRunner

    from toolkit.cli.tools import app

    registry = json.loads((REPO / "harness/review-attestation.json").read_text())
    escape = registry["escape"]
    payload = {
        "number": 2206,
        "state": "OPEN",
        "labels": [{"name": escape["label"]}],
        "body": f"{escape['section']}\n\nEvery file matches the reviewer's ignore glob.",
        "comments": [{"author": {"login": "coderabbitai"}, "body": "<!-- rate limited by coderabbit.ai -->"}],
        "reviews": [],
        "author": {"login": "mlorentedev"},
        "files": [{"path": "infra/config/secrets/prod.enc.yaml"}],
    }
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(payload))
    state_file = tmp_path / "state"

    result = CliRunner().invoke(
        app, ["review-attestation", "--payload-file", str(payload_file), "--state-file", str(state_file)]
    )

    assert result.exit_code == 0, result.output
    assert state_file.read_text().strip() == "disclosed"
