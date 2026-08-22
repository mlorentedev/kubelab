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
