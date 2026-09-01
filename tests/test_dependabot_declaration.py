"""Skipping the reviewer on bot PRs is only half a decision (CI-GATE-015, #1364).

A `pull_request` raised by Dependabot reads the DEPENDABOT secret store, which
this repository never filled, so `NAN_API_KEY` resolves to an empty string and
the reviewer cannot run. Measured 2026-08-24 on #1358-#1362: the run log prints
`Secret source: Dependabot` and `OPENAI__KEY:` with nothing after it.

The reviewer is therefore skipped — and skipping it without declaring the
consequence would leave every bot PR red at the attestation gate, or worse,
quietly merged with nobody having said so. These guards hold the two halves
together: the exclusion exists, the declaration exists, and neither one names the
escape strings itself.
"""

from __future__ import annotations

import json
import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REVIEWER = REPO_ROOT / ".github/workflows/pr-agent.yml"
DECLARER = REPO_ROOT / ".github/workflows/dependabot-declare-unreviewed.yml"
PIPELINE = REPO_ROOT / ".github/workflows/ci-pipeline.yml"
REGISTRY = REPO_ROOT / "harness/review-attestation.json"

_BOT = "dependabot[bot]"


def _load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_reviewer_skips_dependabot_on_the_pull_request_path() -> None:
    condition = _load(REVIEWER)["jobs"]["review"]["if"]

    assert f"github.actor != '{_BOT}'" in condition, (
        "pr-agent would run on Dependabot PRs, where it has no model credential: "
        "the job fails, and the attestation gate then reports a PR nobody could review as unreviewed"
    )


def test_a_human_can_still_ask_for_a_review_on_a_bot_pr() -> None:
    """`/review` runs in base-repo context and DOES carry the credential.

    The exclusion belongs to the `pull_request` branch of the condition only. If
    it ever migrates to the whole expression, a maintainer who explicitly asks
    for a review on a dependency bump would be silently refused.
    """
    condition = _load(REVIEWER)["jobs"]["review"]["if"]
    pull_request_branch, _, comment_branch = condition.partition("|| (github.event_name == 'issue_comment'")

    assert f"github.actor != '{_BOT}'" in pull_request_branch
    assert f"github.actor != '{_BOT}'" not in comment_branch, (
        "a human typing /review must not be blocked by the bot exclusion"
    )


def test_the_declaration_workflow_only_ever_runs_for_the_bot() -> None:
    """The whole safety property. Widened, this labels human PRs `merged-unreviewed`."""
    job = _load(DECLARER)["jobs"]["declare"]

    assert job["if"].strip() == f"github.actor == '{_BOT}'"


def test_the_declaration_reads_the_escape_from_the_registry() -> None:
    """Never its own copy of the label or the heading.

    The gate computes its verdict from `harness/review-attestation.json`. A
    second declaration here would drift, and it would drift silently in the worst
    direction: this workflow reporting success while the PR reads unreviewed
    forever.
    """
    body = DECLARER.read_text(encoding="utf-8")
    escape = json.loads(REGISTRY.read_text(encoding="utf-8"))["escape"]

    assert "harness/review-attestation.json" in body
    assert ".escape.label" in body and ".escape.section" in body
    assert escape["label"] not in body, f"{escape['label']!r} is hardcoded; it must come from the registry"
    assert escape["section"] not in body, f"{escape['section']!r} is hardcoded; it must come from the registry"


def test_the_declaration_can_write_what_it_needs_and_no_more() -> None:
    declared = _load(DECLARER)["permissions"]

    assert declared["pull-requests"] == "write", "it adds a label and edits the body"
    assert declared["contents"] == "read", "it never needs to write to the repository"


def test_the_untrusted_body_is_never_interpolated_into_a_shell() -> None:
    """`github.event.pull_request.body` expanded inside `run:` is a shell injection.

    The body is fetched into a file instead. This asserts the shape rather than
    the intent, because the intent is what erodes when someone adds a step.
    """
    body = DECLARER.read_text(encoding="utf-8")

    assert "${{ github.event.pull_request.body" not in body
    assert "${{ github.event.pull_request.title" not in body


def test_the_declaration_verifies_the_label_actually_landed() -> None:
    """A zero exit code from the write is not evidence the label is on the PR.

    Measured on #1486-#1490 (CI-GATE-016): the step that adds the escape label
    had never succeeded since the workflow shipped, and nothing in this job
    noticed. The job's own verdict was irrelevant to that — what a reader saw
    was the *gate* going red on every dependency bump and blaming the pull
    request, because the escape is a label AND a section and only one of them
    arrived.

    This is the shape `pr-agent.yml` already uses for the same contradiction
    ("Fail if no review was published", #1180): the step that produces a
    durable artefact reads the artefact back, so a write that did not land
    turns this job red and names its own cause instead of leaving a green job
    beside a permanently red gate.
    """
    steps = _load(DECLARER)["jobs"]["declare"]["steps"]
    script = "\n".join(str(step.get("run") or "") for step in steps if isinstance(step, dict))

    writes = re.findall(r"gh api -X POST \"repos/\$\{GITHUB_REPOSITORY\}/issues/\$\{PR_NUMBER\}/labels\"", script)
    reads = re.findall(r"gh api \"repos/\$\{GITHUB_REPOSITORY\}/issues/\$\{PR_NUMBER\}/labels\"", script)
    assert writes and reads, (
        "the escape label is written and never read back: the job can report "
        "success on a declaration GitHub never applied"
    )
    # Keyed to the label it just added, read from the registry, not to a name
    # copied into this file — and non-zero when it is absent.
    assert re.search(r"grep -qxF \"\$LABEL\"", script), "the read-back must test for the registry's own escape label"
    assert "::error" in script and re.search(r"\bexit 1\b", script), (
        "a label that did not land must fail the job with a message, not print and pass"
    )


def test_the_declaration_writes_pr_fields_through_rest_not_the_porcelain() -> None:
    """`gh pr edit` cannot write a PR field on this repository (lesson-002).

    It reads the PR before mutating it with a GraphQL query that asks for
    `repository.pullRequest.projectCards`; the API has refused that field since
    the Projects-classic sunset, so the command dies on its own read and the
    edit never happens — while printing an error about a board nobody is using.
    Measured on gh 2.46.0, the version lesson-002 was written against.

    CI-GATE-016 is why this is asserted rather than assumed: the label step
    failed one stage earlier, on repository resolution, so the known-broken
    command was never reached in CI. Fix only the context and the job keeps
    failing, quietly differently.
    """
    steps = _load(DECLARER)["jobs"]["declare"]["steps"]
    script = "\n".join(str(step.get("run") or "") for step in steps if isinstance(step, dict))
    commands = [ln.strip() for ln in script.splitlines() if ln.strip().startswith("gh ")]

    assert commands, "no gh calls left in the declaring job, so the guards above assert nothing"
    assert [c for c in commands if c.startswith("gh pr edit")] == [], (
        "lesson-002: gh pr edit applies nothing on this repository; use "
        "gh api -X POST repos/OWNER/REPO/issues/<n>/labels -f 'labels[]=<label>'"
    )


def test_the_publish_job_does_not_run_for_the_bot() -> None:
    """Its registry login reads the same empty secret store.

    Skipping loses nothing: the app's own CI job builds the image on every PR,
    and a bump's image is published from master after it merges.
    """
    condition = _load(PIPELINE)["jobs"]["call-publish"]["if"]

    assert f"github.actor != '{_BOT}'" in condition
