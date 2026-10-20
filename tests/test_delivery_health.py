"""#1682 — the watched set is derived, and the verdicts distinguish silence.

Two things are pinned here. The **derivation** must return the delivery lanes
that actually exist in this repository, so a fifth one is either picked up
automatically or turns this red for a human to decide; and the **classification**
must keep "never ran", "still running" and "never started" apart, because
collapsing any two of them reproduces #1666 in the checker itself.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

from toolkit.features import delivery_health as dh

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"


def _load(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _resolve(uses: str) -> dict[str, Any] | None:
    if not uses.startswith("./"):
        return None
    path = REPO / uses[2:]
    return _load(path) if path.exists() else None


# --- the derivation, against the real tree -----------------------------------

#: What the predicate must return today. Named, so that a delivery lane leaving
#: the set is as red as one arriving — a count would be satisfied by any five.
#: `delivery-health.yml` is this checker's own workflow: the predicate cannot
#: reach it, and a watcher blind to its own startup_failure is the defect one
#: level up. See `delivery_health.SELF`.
EXPECTED = {
    "delivery-health.yml",
    "product-image-receiver.yml",
    "promote-prod.yml",
    "release.yml",
    "staging-deploy.yml",
    "web-image-receiver.yml",
}


def test_the_scan_finds_the_workflow_tree_at_all():
    """Without this, a moved directory turns every assertion below into a pass."""
    found = sorted(WORKFLOWS.glob("*.y*ml"))
    assert len(found) > 10, (
        f"only {len(found)} workflow files under {WORKFLOWS}; the scan has drifted "
        "and the derivation below is measuring nothing"
    )


def test_the_derived_set_is_exactly_the_delivery_lanes():
    # Verified by mutation, and note WHICH mutation: `staging-deploy.yml` and
    # `release.yml` reach delivery by BOTH routes, so cutting one leaves them in
    # the set and the test stays green. That is the predicate being redundant,
    # not the test being vacuous — the first attempt at this mutation cut only
    # `ci-publish.yml` from `staging-deploy.yml` and proved nothing. Mutate a
    # single-route lane (`promote-prod.yml`, `web-image-receiver.yml`, which
    # reach it only through `deployment promote`) and this goes red.
    got = set(dh.watched(_load, sorted(WORKFLOWS.glob("*.y*ml")), _resolve))
    assert got == EXPECTED, (
        f"derived {sorted(got)}, expected {sorted(EXPECTED)}.\n\n"
        "A workflow that gained or lost a path to `ci-publish.yml` or to "
        "`toolkit deployment promote` changed what this check covers. Decide "
        "deliberately, then update EXPECTED — do not widen the predicate to make "
        "this pass."
    )


@pytest.mark.parametrize(
    "name, why",
    [
        ("ci-publish.yml", "workflow_call only: no runs of its own, total_count 0"),
        ("ci-pipeline.yml", "workflow_call only: its jobs belong to the caller's run"),
        ("pr-agent.yml", "'deployment promote' appears in a COMMENT, not a step"),
        (
            "ci.yml",
            "publishes transitively, but produces required contexts, so a "
            "startup_failure blocks the next PR — its silence is bounded",
        ),
        ("review-attestation.yml", "same reason as ci.yml: it publishes a required status"),
        ("add-to-project.yml", "issue-triggered helper; 'never ran' means nobody filed an issue"),
    ],
)
def test_these_are_deliberately_not_watched(name: str, why: str):
    """Each exclusion has a reason, and the reason is the test's argument."""
    assert name not in EXPECTED, why


# --- the two traps the predicate had to survive ------------------------------


def test_on_parses_as_the_boolean_true_and_triggers_still_reads_it():
    """YAML 1.1 resolves the unquoted key `on` to True.

    Reading `workflow["on"]` alone returns nothing for every real file here, so
    every workflow looks attended and the watched set comes back empty — a check
    that passes by measuring nothing.
    """
    parsed = yaml.safe_load("on:\n  push:\n    branches: [master]\njobs: {}\n")
    assert "on" not in parsed and True in parsed, "PyYAML stopped folding `on` to True"
    assert dh.triggers(parsed) == {"push"}


def test_a_comment_mentioning_promote_is_not_a_delivery_step():
    """The text grep that matched `pr-agent.yml` must not be reproduced."""
    workflow = yaml.safe_load(
        "on:\n  push:\njobs:\n"
        "  talk:\n    steps:\n"
        "      # written by `toolkit deployment promote` and already guaranteed\n"
        "      - run: echo nothing\n"
    )
    assert not dh.reaches_delivery(workflow, lambda _: None)


def test_a_transitive_call_still_reaches_the_publisher():
    caller = {"on": {"push": None}, "jobs": {"a": {"uses": "./.github/workflows/mid.yml"}}}
    mid = {"on": {"workflow_call": None}, "jobs": {"b": {"uses": "./.github/workflows/ci-publish.yml"}}}
    assert dh.reaches_delivery(caller, lambda uses: mid if "mid" in uses else None)


def test_a_cycle_between_workflows_does_not_recurse_forever():
    a = {"jobs": {"j": {"uses": "./.github/workflows/b.yml"}}}
    b = {"jobs": {"j": {"uses": "./.github/workflows/a.yml"}}}
    resolve = lambda uses: b if uses.endswith("b.yml") else a  # noqa: E731
    assert dh.reaches_delivery(a, resolve) is False


def test_the_checker_watches_itself():
    """Not derivable, and not an oversight.

    The watcher is unattended and touches neither the publisher nor `promote`,
    so the predicate cannot reach it. A checker silent about its own
    startup_failure is #1666 one level up.
    """
    assert dh.SELF in dh.watched(_load, [], lambda _: None)


# --- the verdicts ------------------------------------------------------------


def test_a_startup_failure_is_refused():
    v = dh.classify("staging-deploy.yml", [{"conclusion": "startup_failure", "html_url": "u"}])
    assert v.state == "startup_failure" and not v.ok


def test_never_ran_is_reported_distinctly_from_healthy():
    """AC3. Absence of a run is not evidence of health."""
    v = dh.classify("promote-prod.yml", [])
    assert v.state == "never_ran" and not v.ok
    assert v.state != dh.classify("x", [{"conclusion": "success"}]).state


def test_a_run_still_executing_is_not_a_verdict():
    """`conclusion: null` measured on `ci.yml`. Reading it as failure cries wolf."""
    v = dh.classify("release.yml", [{"conclusion": None, "html_url": "u"}])
    assert v.state == "in_progress" and v.ok


def test_an_ordinary_failure_is_not_this_check_s_business():
    """A red run reports itself through checks; a second channel is noise."""
    v = dh.classify("release.yml", [{"conclusion": "failure"}])
    assert v.ok, "an ordinary failure must not be escalated here"


def test_only_the_newest_run_decides():
    runs = [{"conclusion": "success"}, {"conclusion": "startup_failure"}]
    assert dh.classify("w", runs).ok


def test_a_404_is_an_answer_and_not_a_transport_failure(monkeypatch):
    """GitHub holding no record of a workflow means it never ran.

    Raising instead would collapse "the answer is none" into "I could not ask" —
    the confusion this module exists to end. It is also how this checker
    bootstraps: before its own workflow merges, the remote does not know it.
    """
    import subprocess

    class Proc:
        returncode = 1
        stdout = ""
        stderr = "gh: Not Found (HTTP 404)"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc())
    assert dh.fetch_runs("o/r", "delivery-health.yml") == []
    assert dh.classify("delivery-health.yml", []).state == "never_ran"


def test_a_real_transport_failure_still_refuses_to_guess(monkeypatch):
    import subprocess

    class Proc:
        returncode = 1
        stdout = ""
        stderr = "gh: API rate limit exceeded"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(dh.WorkflowError):
        dh.fetch_runs("o/r", "release.yml")


def test_the_checker_reads_its_own_in_flight_run_as_not_a_verdict():
    """Why watching itself does not deadlock.

    When this workflow executes, that execution IS a run of it, reported with
    `conclusion: null` while in progress. Read as a failure it would be red on
    every single run; read as "not a verdict" it is correct.
    """
    v = dh.classify(dh.SELF, [{"conclusion": None, "html_url": "u"}])
    assert v.ok and v.state == "in_progress"


def test_an_empty_verdict_set_is_unanswerable_not_clean():
    """2, never 0. A derivation that found nothing has failed to ask."""
    assert dh.worst([]) == 2
    assert dh.worst([dh.classify("w", [{"conclusion": "success"}])]) == 0
    assert dh.worst([dh.classify("w", [])]) == 1


def test_the_cycle_guard_keys_on_the_file_not_its_spelling():
    """Two spellings of one path must not defeat the guard.

    Theoretical in this repository — Actions requires the `./` prefix — but a
    cycle guard that fails does not fail loudly, it recurses. Raised by PR-Agent
    on #1696.
    """
    a = {"jobs": {"j": {"uses": "./.github/workflows/b.yml"}}}
    b = {"jobs": {"j": {"uses": ".github/workflows/./b.yml"}}}  # same file, spelled twice
    assert dh._normalise("./.github/workflows/b.yml") == dh._normalise(".github/workflows/./b.yml")
    assert dh.reaches_delivery(a, lambda _: b) is False
