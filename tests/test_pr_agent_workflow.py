"""The reviewer and the gate agree on a name, or re-evaluation fails silently.

TOOL-021 Part 2 (#1140). `review-attestation.yml` re-reads its verdict on
`workflow_run: workflows: [pr-agent]`, because comments authored with
`GITHUB_TOKEN` emit no events and the gate would otherwise compute a verdict
seconds after the PR opens and never revise it.

That makes the reviewer workflow's `name:` a two-file agreement. Rename either
side and nothing errors: the reviewer still reviews, the gate simply never looks
again, and every PR it reviewed reads as unreviewed. A guarantee that degrades
into silence when a string drifts is the failure class this repo has spent days
cataloguing, so it is asserted rather than left as a convention.
"""

from __future__ import annotations

import json
import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REVIEWER = REPO_ROOT / ".github/workflows/pr-agent.yml"
GATE = REPO_ROOT / ".github/workflows/review-attestation.yml"


def _load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_gate_re_evaluates_on_the_reviewer_workflow_by_its_real_name() -> None:
    reviewer_name = _load(REVIEWER)["name"]
    gate = _load(GATE)
    # PyYAML parses a bare `on:` key as the boolean True (the Norway problem's
    # cousin). Accept either spelling so the test does not depend on quoting.
    triggers = gate.get("on") or gate.get(True)
    watched = (triggers or {}).get("workflow_run", {}).get("workflows", [])
    assert reviewer_name in watched, (
        f"review-attestation.yml watches {watched!r}, but the reviewer workflow is "
        f"named {reviewer_name!r}. The gate would never re-read its verdict, and "
        "every PR PR-Agent reviewed would report as unreviewed — silently."
    )


def test_the_reviewer_skips_release_branches_at_the_job_level() -> None:
    """The config-level setting for this was measured inert upstream.

    `ignore_pr_source_branches` is loaded and never consulted on the Action path,
    so porting it would install a setting that looks like a decision and asserts
    nothing (dotfiles #1073). The `if:` is the replacement, at the layer that
    runs. Without it PR-Agent reports "none of the above requirements are
    fulfilled" on every release PR, structurally.
    """
    condition = _load(REVIEWER)["jobs"]["review"]["if"]
    assert "release-please--" in condition, (
        "the release-branch skip is gone from the job condition; release PRs will "
        "be reviewed and will collect structural ticket-compliance noise"
    )


def test_the_inert_upstream_setting_was_not_ported() -> None:
    """Guard against someone 'restoring' it from upstream later.

    It is not a missing feature — it is a measured no-op, and re-adding it would
    make the job condition above look redundant to the next reader.
    """
    config = (REPO_ROOT / ".pr_agent.toml").read_text(encoding="utf-8")
    for line in config.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("ignore_pr_source_branches"), (
            "ignore_pr_source_branches is set; it was measured inert on the "
            "GitHub Action path. The job-level `if:` in pr-agent.yml is what works."
        )


def test_credential_material_is_excluded_from_the_model_call() -> None:
    """kubelab is public, so the source is not the concern. Credentials are."""
    import tomllib

    config = tomllib.loads((REPO_ROOT / ".pr_agent.toml").read_text(encoding="utf-8"))
    globs = config.get("ignore", {}).get("glob", [])
    for required in ("infra/config/secrets/**", "**/*.pem"):
        assert required in globs, f"{required} is not excluded; SOPS ciphertext and private keys would be sent for review"


def test_the_action_is_pinned_by_sha_not_by_tag() -> None:
    """A tag is mutable; this job holds NAN_API_KEY on a public repository.

    Whoever can move the tag can change what runs with that credential. Upstream
    pins by tag — this is a place the port should exceed its source, and a test
    is what stops a later "bump" quietly reverting to one.
    """
    used = [s for s in _load(REVIEWER)["jobs"]["review"]["steps"] if "uses" in s]
    assert used, "no `uses:` step in the reviewer job"
    # EVERY `uses:` step, not the first one. This asserted `next(...)` while the
    # job had exactly one action; the PR-number upload (#1184) made it two, and
    # the first is now that upload -- so the original form would have gone on
    # passing while PR-Agent itself reverted to a mutable tag. A guard that stops
    # covering its subject without failing is the class lesson-357 catalogues.
    for step in used:
        ref = step["uses"].split("@", 1)[1]
        assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), (
            f"{step['uses']!r} is pinned to {ref!r}, which is not a commit SHA. "
            "Every action in this job runs alongside NAN_API_KEY on a public "
            "repo, so a mutable tag decides what executes with that credential."
        )


def test_the_reviewer_verifies_it_actually_published() -> None:
    """PR-Agent reports SUCCESS for starting and finishing, not for publishing.

    Observed on #1180: green job, `## PR Code Suggestions` posted, zero comments
    carrying the review marker, and the attestation gate correctly red — a green
    reviewer sitting beside a red gate with nothing to explain the contradiction.
    The gate protects the merge; this step exists so the reviewer's own job goes
    red and names the cause.
    """
    steps = _load(REVIEWER)["jobs"]["review"]["steps"]
    verifier = next((s for s in steps if "no review was published" in s.get("name", "")), None)
    assert verifier is not None, "nothing checks that PR-Agent published anything"
    assert "always()" in verifier["if"], "must run even when the reviewer step failed"


def test_the_publish_check_reads_the_marker_from_the_shared_registry() -> None:
    """The reviewer and its judge must not disagree about what a review is.

    A hardcoded marker string here would be a second source of truth, and the
    failure it produces is invisible: the reviewer would pass its own check
    while the gate reads the PR unreviewed.
    """
    steps = _load(REVIEWER)["jobs"]["review"]["steps"]
    verifier = next(s for s in steps if "no review was published" in s.get("name", ""))
    assert "harness/review-attestation.json" in verifier["run"]
    assert "review_markers" in verifier["run"]
    # The marker itself must NOT appear as a literal in the workflow.
    registry = json.loads((REPO_ROOT / "harness/review-attestation.json").read_text())
    marker = next(
        r["review_markers"][0]
        for r in registry["reviewers"]
        if r["login"] == "github-actions" and r.get("review_markers")
    )
    assert marker not in verifier["run"], (
        f"the marker {marker!r} is hardcoded in the workflow; the registry is the SSOT"
    )


def test_the_publish_check_does_not_read_an_attacker_influenced_ref() -> None:
    """It reads a file that decides what counts as a review, so the ref it reads
    from must not be one a PR author picks. `base.ref` is exactly that — the
    upstream uses it, review-attestation.yml already rejected it, and the port
    takes the hardened form."""
    steps = _load(REVIEWER)["jobs"]["review"]["steps"]
    verifier = next(s for s in steps if "no review was published" in s.get("name", ""))
    assert "base.ref" not in str(verifier.get("env", {}))
    assert "default_branch" in str(verifier["env"]["BASE_REF"])


def test_inference_runs_are_queued_not_run_in_parallel() -> None:
    """The NaN cluster allows 5 simultaneous requests and is shared. Exhausting
    them is the diagnosed cause of the publish-nothing failure above, so the
    reviewer job queues globally instead of racing itself across PRs."""
    job = _load(REVIEWER)["jobs"]["review"]
    assert job["concurrency"]["group"] == "pr-agent-nan-inference", (
        "the group must NOT be keyed per PR — that is the workflow-level group's "
        "job, and it is the cross-PR pile-up that exhausts the cluster"
    )
    assert job["concurrency"]["cancel-in-progress"] is False, "queue, never cancel"


def test_the_gate_does_not_cancel_on_events_that_add_evidence() -> None:
    """A comment, a label or an edit is new evidence about the SAME commit.
    Cancelling there is what put `cancelled` in `gh pr checks`' fail column on a
    healthy gate — repeatedly, because a reviewer speaking is itself a trigger.
    """
    cancel = str(_load(GATE)["concurrency"]["cancel-in-progress"])
    for action in ("labeled", "unlabeled", "edited", "created"):
        assert action in cancel, f"{action} would still cancel an in-flight run"
    # A push must still cancel: it replaces the commit being judged.
    assert "synchronize" not in cancel


def test_an_unreviewed_pr_does_not_fail_the_gate_job() -> None:
    """The verdict belongs in the commit status, which branch protection reads
    and which already blocks the merge. Failing the job too republished it into
    the checks list, where red means "something is broken" — so the normal
    state of a healthy, not-yet-reviewed PR was a red job.

    That is how a red signal stops being read. This gate exists because a green
    check nobody questioned let 35 of 40 PRs merge unreviewed; buying that back
    with indifference toward red is not a trade worth making.
    """
    steps = _load(GATE)["jobs"]["attestation"]["steps"]
    final = next(s for s in steps if "could not answer" in s.get("name", ""))
    run = final["run"]
    # The exit-0 condition is pinned EXACTLY, not matched as a substring.
    #
    # Substring assertions were the first version here and review caught them:
    # widening the guard to `... || [ "$CODE" = "2" ]` keeps every substring
    # present, so the tests stay green while `::error::` becomes unreachable
    # and the "could not determine" case goes quietly green — the one thing
    # this change says must stay loud. `assert 'exit 0' in run` was worse than
    # weak, it was vacuous: the pre-fix shape `[ "$CODE" = "0" ] && exit 0`
    # contained it too, so it could not detect the regression its own comment
    # named.
    condition = re.search(r"if (.+); then\n\s*exit 0", run)
    assert condition, "no exit-0 guard found at all"
    assert condition.group(1) == '[ "$CODE" = "0" ] || [ "$CODE" = "1" ]', (
        "codes 0 and 1 are verdicts and must not fail the job; anything else "
        f"must. Found: {condition.group(1)}"
    )


def test_a_gate_that_cannot_answer_still_fails_the_job() -> None:
    """Code 2 is different in kind from code 1: the classifier could not
    determine the state at all. That is the gate malfunctioning rather than
    reporting, and it is the one case the status alone does not surface — 'I
    could not tell' delivered as silence is the defect this mechanism exists
    to end."""
    steps = _load(GATE)["jobs"]["attestation"]["steps"]
    final = next(s for s in steps if "could not answer" in s.get("name", ""))
    assert 'exit "$CODE"' in final["run"], "a non-verdict exit code must still fail"
    assert "::error::" in final["run"], "and must say so in the log"


# The artifact carrying the PR number from the reviewer to the gate (#1184).
# A literal, deliberately: the point of the assertions below is to anchor both
# workflows to a value neither of them derives. Reading the name out of
# `pr-agent.yml` and asserting the file agrees with itself would pass by
# construction -- the failure class lesson-357 catalogues.
ARTIFACT_NAME = "pr-number"


def _review_steps() -> list[dict]:
    return _load(REVIEWER)["jobs"]["review"]["steps"]


def _first_index(steps: list[dict], prefix: str) -> int:
    for i, step in enumerate(steps):
        if str(step.get("uses", "")).startswith(prefix):
            return i
    return -1


def test_the_pr_number_is_uploaded_under_the_name_the_gate_reads() -> None:
    """A `/review` reaches the gate with no PR reference unless this runs.

    `workflow_run` does not propagate the triggering event's context: a run
    started by `issue_comment` is associated with the default branch, so the
    gate sees `pull_requests[]` empty and `head_sha` at master, and correctly
    skips. The reference is not lost in transit, it never enters it — which is
    why the fix is on the SENDING side and why this assertion lives here.
    """
    uploads = [
        s for s in _review_steps() if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 1, (
        f"expected exactly one upload-artifact step in pr-agent.yml, found "
        f"{len(uploads)}. The gate downloads one artifact by name; two would make "
        f"which one it gets an ordering accident."
    )
    assert uploads[0].get("with", {}).get("name") == ARTIFACT_NAME, (
        f"the PR-number artifact must be named {ARTIFACT_NAME!r}: the gate "
        f"downloads by that literal string. Renaming one side degrades into "
        f"silence — the reviewer reviews, the gate finds nothing, and the PR "
        f"reads unreviewed."
    )


def test_the_upload_precedes_the_reviewer_so_a_cancelled_run_still_carries_it() -> None:
    """Ordering is load-bearing, not tidiness.

    This job is cancellable by the workflow-level concurrency group, and
    `workflow_run: [completed]` fires for cancelled runs too. If the upload sat
    after PR-Agent, a run cancelled mid-review would reach the gate with no
    artifact — precisely the case the gate most needs to judge.
    """
    steps = _review_steps()
    upload = _first_index(steps, "actions/upload-artifact@")
    reviewer = _first_index(steps, "The-PR-Agent/pr-agent@")
    assert upload >= 0, "no upload-artifact step in pr-agent.yml"
    assert reviewer >= 0, "no PR-Agent step in pr-agent.yml"
    assert upload < reviewer, (
        "the PR-number upload must run BEFORE PR-Agent. A run cancelled during "
        "the review would otherwise produce no artifact, and the gate would skip "
        "the PR it most needed to judge."
    )
