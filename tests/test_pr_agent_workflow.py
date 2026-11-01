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
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REVIEWER = REPO_ROOT / ".github/workflows/pr-agent.yml"
GATE = REPO_ROOT / ".github/workflows/review-attestation.yml"
PR_AGENT_CONFIG = REPO_ROOT / ".pr_agent.toml"
REVIEWER_POOL = REPO_ROOT / "harness/reviewer-pool.json"
PUBLISH_GUARD = REPO_ROOT / "scripts/pr-agent-publish-guard.sh"
ROUTE = REPO_ROOT / "scripts/pr-agent-route.sh"


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


def test_the_reviewer_skips_generated_deploy_and_promote_branches() -> None:
    """Generated version bumps carry nothing a review could act on (DELIVERY-004).

    Two lines: an app version in `values/<env>.yaml` and the same value in the
    regenerated overlay, written by `toolkit deployment promote` and already
    guaranteed byte-for-byte against the generator by the config-drift gate. 23
    of the last 60 PRs here were these, and each takes the ONE pending slot of
    the `pr-agent-nan-inference` group — so a generated bump does not merely
    waste a review, it displaces a human PR's (#1203).

    Both prefixes are asserted, not just one. They are opened by two different
    workflows (`product-image-receiver.yml`, `promote-prod.yml`), so one can be
    dropped from the condition while the other keeps this test green — which is
    the failure this repository keeps finding, an assertion that covers less
    than its name claims.
    """
    condition = _load(REVIEWER)["jobs"]["review"]["if"]
    for prefix in ("deploy/", "promote/"):
        assert f"'{prefix}'" in condition, (
            f"the {prefix} skip is gone from the job condition; generated version "
            f"bumps will be reviewed again and will displace human PRs from the "
            f"single pending inference slot"
        )


def test_the_reviewer_skips_by_branch_but_the_gate_never_does() -> None:
    """The asymmetry is deliberate and must not be 'made consistent'.

    Matching a branch name HERE is safe because gaming it forfeits a review: the
    attestation gate then reports the PR unreviewed and goes red, so the cost
    lands on whoever gamed it. Matching a branch name in the GATE would do the
    opposite — it would grant a bypass to anyone who can push a branch, and
    `RELEASE_PLEASE_TOKEN` is a PAT.

    So the gate matches on the exact changed-file set and this workflow matches
    on a name, and a future edit that unifies them would silently convert a
    protection into a hole. This asserts the gate has not acquired a branch rule.
    """
    gate_module = (REPO_ROOT / "toolkit" / "features" / "review_attestation.py").read_text(encoding="utf-8")
    for token in ("head_ref", "headRefName", "startswith('deploy/", 'startswith("deploy/'):
        assert token not in gate_module, (
            f"the attestation gate now references {token!r}. Branch-based matching in "
            f"the GATE is a bypass for anyone who can name a branch — the reviewer "
            f"may match on a name, this must not."
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


def test_the_reviewer_is_asked_about_verdicts_that_needed_no_change() -> None:
    """The one review dimension this repo has shipped four bugs against.

    **This asserts the instruction is DECLARED, not that it works.** No test can
    check the second — whether a model acts on a prompt line is measured over
    reviews, not asserted in CI, and this file's own history says so: upstream's
    "HARNESS COMPLIANCE" preamble was asked for on every review and delivered 1
    time in 16. So read this as a guard against silent deletion during a config
    tidy, which is the only failure mode it can actually cover.

    If the bullet is ever measured inert the way that preamble was, delete it and
    delete this test with it — an instruction that looks like a control and is
    not is the exact thing it was added to catch.
    """
    import tomllib

    config = tomllib.loads((REPO_ROOT / ".pr_agent.toml").read_text(encoding="utf-8"))
    instructions = config["pr_reviewer"]["extra_instructions"]
    assert "WITHOUT the change under" in instructions, (
        "the reviewer is no longer asked whether a check's verdict could be "
        "produced without the change under test -- see the measured instances "
        "in .pr_agent.toml's comment above the block"
    )


def test_credential_material_is_excluded_from_the_model_call() -> None:
    """kubelab is public, so the source is not the concern. Credentials are."""
    import tomllib

    config = tomllib.loads((REPO_ROOT / ".pr_agent.toml").read_text(encoding="utf-8"))
    globs = config.get("ignore", {}).get("glob", [])
    for required in ("infra/config/secrets/**", "**/*.pem"):
        assert required in globs, (
            f"{required} is not excluded; SOPS ciphertext and private keys would be sent for review"
        )


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
    # One definition of "published", shared with the probes between attempts
    # (TOOL-082): the step runs the script, and the script reads the registry.
    assert verifier["run"].strip() == "./scripts/pr-agent-publish-guard.sh"
    guard = PUBLISH_GUARD.read_text(encoding="utf-8")
    assert "harness/review-attestation.json" in guard
    assert "review_markers" in guard
    # The marker itself must NOT appear as a literal in the workflow or the script.
    registry = json.loads((REPO_ROOT / "harness/review-attestation.json").read_text(encoding="utf-8"))
    marker = next(
        r["review_markers"][0]
        for r in registry["reviewers"]
        if r["login"] == "github-actions" and r.get("review_markers")
    )
    for text in (REVIEWER.read_text(encoding="utf-8"), guard):
        assert marker not in text, f"the marker {marker!r} is hardcoded; the registry is the SSOT"


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
    assert job["concurrency"]["cancel-in-progress"] is False, "never cancel the review that is running"
    # TOOL-108 (#2179): without it GitHub keeps one running and ONE pending run,
    # and a third request silently cancels the second before it gets a runner.
    assert job["concurrency"].get("queue") == "max", (
        "without `queue: max` the group holds one pending run, and a newer one discards it"
    )


def test_the_queue_is_not_beside_a_cancelling_group() -> None:
    """GitHub refuses `queue: max` in a group that cancels in progress, so the
    queue lives on the job and the workflow-level group keeps cancelling."""
    workflow = _load(REVIEWER)
    assert "queue" not in workflow["concurrency"]
    assert workflow["concurrency"]["cancel-in-progress"] is True
    # The queue itself: without it the shared group keeps one pending run and
    # discards the rest (#2179).
    job = workflow["jobs"]["review"]["concurrency"]
    assert job == {"group": "pr-agent-nan-inference", "cancel-in-progress": False, "queue": "max"}


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
        f"codes 0 and 1 are verdicts and must not fail the job; anything else must. Found: {condition.group(1)}"
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
    uploads = [s for s in _review_steps() if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
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


_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="these steps are bash scripts")


# --- CI-GATE-017 (#1527): a diff entirely inside .pr_agent.toml's [ignore] ---
# glob has nothing for PR-Agent to review. Measured on #1514 and #1523, both
# single-file PRs wholly inside infra/config/secrets/**: PR-Agent's own
# _prepare_prediction found an empty reviewable set after the ignore filter,
# published nothing, and the existing guard failed for a reason neither of
# its own two documented causes (saturation, empty-body-on-200) names.


def _reviewer_step(name_substr: str) -> dict:
    """Found by a distinctive substring of `name:`, same convention as
    `_gate_resolve_step`'s search-by-`id` below — a rename must not silently
    skip these."""
    return next(s for s in _review_steps() if name_substr in s.get("name", ""))


def test_the_reviewable_check_does_not_read_an_attacker_influenced_ref() -> None:
    """Same property `test_the_publish_check_does_not_read_an_attacker_influenced_ref`
    asserts for the guard below it, applied to the new step: reading the
    ignore list from the PR's own branch would let an author add `"**"` to
    `.pr_agent.toml` there, make every file "excluded", and auto-skip straight
    to the escape with a green gate and no review ever attempted."""
    step = _reviewer_step("Determine whether the diff has anything to review")
    assert "base.ref" not in str(step.get("env", {}))
    assert "default_branch" in str(step["env"]["BASE_REF"])


def test_the_reviewable_check_is_not_always_and_fails_closed() -> None:
    """`always()` would run this even when an earlier step (like recording the
    PR number) errored. Without it, a failure inside this step itself — the
    `gh api` calls failing, say — fails the step and leaves
    `steps.reviewable.outputs.any` unset, which is neither 'true' nor 'false'.
    Both the PR-Agent step and the declare-unreviewed step below are gated on
    an exact string match against that output, so an unset value skips both
    and the job goes red instead of silently declaring or silently reviewing.
    """
    step = _reviewer_step("Determine whether the diff has anything to review")
    assert "always()" not in str(step.get("if", ""))


def test_an_improve_comment_reaches_the_reviewer() -> None:
    """`/improve` is the only way suggestions run, because `auto_improve` is off
    (#1180). Its comment has to pass the reviewable check, since PR-Agent is
    gated on that check's output: from #1528 until #2187 the check admitted
    `/review` alone, and `/improve` skipped every step and reported success."""
    condition = " ".join(str(_reviewer_step("Determine whether the diff has anything to review")["if"]).split())
    assert "contains(github.event.comment.body, '/improve')" in condition


@pytest.mark.parametrize(
    "name", ["Fail if no review was published", "Declare unreviewed", "Clear a stale unreviewed-merge declaration"]
)
def test_an_improve_comment_never_touches_the_attestation(name: str) -> None:
    """A `/improve` run publishes suggestions, never a review, so the steps that
    decide or declare the review stay on `/review`: admitting `/improve` there
    would fail a reviewed PR red, or declare it unreviewed.

    The condition is evaluated, not searched for a token: since #2187 the
    reviewable check answers for `/improve` too, so a step that keys on its
    output alone would run on an `/improve` comment without naming it."""
    condition = str(_reviewer_step(name)["if"])
    for reviewable in ("true", "false"):
        steps = {"reviewable": {"outputs": {"any": reviewable}}, "credential": {"outcome": "success"}}
        improve = _comment_run(body="/improve", association="MEMBER")
        review = _comment_run(body="/review", association="MEMBER")
        assert not _evaluate(condition, improve, steps), f"runs on `/improve` with reviewable={reviewable}"
        if _evaluate(condition, review, steps):
            break
    else:
        pytest.fail("the step runs on no `/review` comment either: the fixture no longer exercises its if:")


def test_pr_agent_only_runs_when_something_is_reviewable() -> None:
    """Every step that probes a provider, draws, reviews or judges the review is
    gated, not only the attempts: an ungated probe would spend a call, and an
    ungated guard would fail a PR whose diff is entirely excluded."""
    guard = next(s for s in _review_job()["steps"] if "no review was published" in s.get("name", ""))
    gated = [*_attempts().values(), *(_step_by_id(i) for i in ("models", "route")), guard]
    gated += [_step_by_id(i) for i in ("published_after_anthropic", "published_after_nan")]
    for step in gated:
        assert "steps.reviewable.outputs.any == 'true'" in " ".join(str(step.get("if", "")).split()), step["name"]


def test_the_guard_skips_when_nothing_was_reviewable() -> None:
    step = _reviewer_step("Fail if no review was published")
    condition = " ".join(str(step["if"]).split())
    assert "steps.reviewable.outputs.any == 'true'" in condition
    assert "always()" in condition, "must still run to catch a REAL publish failure"


def test_declare_unreviewed_step_only_fires_when_nothing_was_reviewable() -> None:
    step = _reviewer_step("Declare unreviewed")
    condition = " ".join(str(step["if"]).split())
    assert "steps.reviewable.outputs.any == 'false'" in condition


def test_declare_unreviewed_step_reads_the_escape_from_the_registry_not_a_literal() -> None:
    """The reviewer and the gate must not disagree about what declares a PR
    unreviewed, same reasoning as the review marker above: a hardcoded label
    or section string here would be a second source of truth that could drift
    from harness/review-attestation.json without either side erroring."""
    step = _reviewer_step("Declare unreviewed")
    assert "harness/review-attestation.json" in step["run"]
    assert "escape.label" in step["run"]
    assert "escape.section" in step["run"]
    registry = json.loads((REPO_ROOT / "harness/review-attestation.json").read_text(encoding="utf-8"))
    assert registry["escape"]["label"] not in step["run"], (
        "the escape label is hardcoded in the workflow; the registry is the SSOT"
    )
    assert registry["escape"]["section"] not in step["run"], (
        "the escape section is hardcoded in the workflow; the registry is the SSOT"
    )


def test_declare_unreviewed_rationale_does_not_point_at_a_dead_end() -> None:
    """dependabot-declare-unreviewed.yml's rationale ends with 'comment
    /review', which works there because a human-triggered run carries the
    credential dependabot's lacks. Here a /review retry hits the SAME ignore
    filter and produces the SAME empty diff, so pointing at it would send the
    reader looking for a review that cannot happen."""
    step = _reviewer_step("Declare unreviewed")
    # Not a bare `"/review" not in ...` check: the registry path itself
    # ("harness/review-attestation.json") contains that substring, which
    # would make the assertion fail on the step's own, unrelated, `gh api`
    # call. The dependabot version's actual dead-end phrase is this one.
    assert "comment `/review`" not in step["run"]
    assert "decrypt" in step["run"] and "lesson-376" in step["run"], (
        "the rationale should point at the verification method that actually "
        "works here (decrypt both sides, diff key names), not at a re-review"
    )


def test_stale_declaration_is_cleared_only_once_reviewable_again() -> None:
    step = _reviewer_step("Clear a stale unreviewed-merge declaration")
    condition = " ".join(str(step["if"]).split())
    assert "steps.reviewable.outputs.any == 'true'" in condition


_REVIEWABLE_GH_STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_CALLS"
case "$*" in
  *"contents/.pr_agent.toml"*) base64 -w0 "$STUB_TOML" ;;
  *"pulls/"*"/files"*)         cat "$STUB_FILES" ;;
  *) exit 1 ;;
esac
"""
# The step pipes this stub's output through `base64 -d` for the first call
# and consumes the second directly, exactly mirroring what `gh api ...
# --jq '.content'` and `gh api ... --jq '.[].filename'` would each already
# have produced — the stub replaces `gh` entirely, so it must answer as the
# real API's `--jq`-filtered output would, not as the raw JSON would.


def _run_reviewable_step(tmp_path: pathlib.Path, toml_text: str, files: list[str]) -> tuple[str | None, list[str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "gh"
    stub.write_text(_REVIEWABLE_GH_STUB, encoding="utf-8")
    stub.chmod(0o755)

    toml_path = tmp_path / "stub_toml.txt"
    toml_path.write_text(toml_text, encoding="utf-8")
    files_path = tmp_path / "stub_files.txt"
    files_path.write_text("".join(f"{f}\n" for f in files), encoding="utf-8")

    output = tmp_path / "github_output"
    output.touch()
    calls = tmp_path / "gh_calls"
    calls.touch()

    step = _reviewer_step("Determine whether the diff has anything to review")
    env = {
        **os.environ,
        "PATH": os.pathsep.join([str(bindir), str(pathlib.Path(sys.executable).parent), os.environ["PATH"]]),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "mlorentedev/kubelab",
        "GH_CALLS": str(calls),
        "GH_TOKEN": "stub",
        "PR_NUMBER": "1514",
        "BASE_REF": "master",
        "STUB_TOML": str(toml_path),
        "STUB_FILES": str(files_path),
    }
    proc = subprocess.run(  # noqa: S603
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"the reviewable step exited {proc.returncode}.\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    parsed = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if "=" in line)
    calls_made = calls.read_text(encoding="utf-8").splitlines()
    return parsed.get("any"), calls_made


_TOML_ONE_GLOB = '[ignore]\nglob = [\n  "infra/config/secrets/**",\n  "**/*.pem",\n]\n'


@_needs_bash
def test_reviewable_step_says_false_when_every_file_is_ignored(
    tmp_path: pathlib.Path,
) -> None:
    """The measured case: #1514 and #1523 each touched exactly
    infra/config/secrets/prod.enc.yaml and nothing else."""
    any_, _ = _run_reviewable_step(tmp_path, _TOML_ONE_GLOB, ["infra/config/secrets/prod.enc.yaml"])
    assert any_ == "false"


@_needs_bash
def test_reviewable_step_says_true_when_one_file_is_not_ignored(
    tmp_path: pathlib.Path,
) -> None:
    """#1525's shape: a secrets file plus a real code change stays reviewable."""
    any_, _ = _run_reviewable_step(
        tmp_path,
        _TOML_ONE_GLOB,
        ["infra/config/secrets/prod.enc.yaml", "toolkit/features/k8s_secrets.py"],
    )
    assert any_ == "true"


@_needs_bash
def test_reviewable_step_says_true_for_a_mixed_secrets_and_docs_pr(
    tmp_path: pathlib.Path,
) -> None:
    """#1517's shape: two secrets files plus a plaintext baseline and test
    file. Mixed PRs must not be swept into the all-ignored case."""
    any_, _ = _run_reviewable_step(
        tmp_path,
        _TOML_ONE_GLOB,
        [
            "infra/config/orphan-secrets-baseline.yaml",
            "infra/config/secrets/common.enc.yaml",
            "infra/config/secrets/staging.enc.yaml",
            "tests/test_orphan_secrets_ratchet.py",
        ],
    )
    assert any_ == "true"


@_needs_bash
def test_reviewable_step_fetches_the_ignore_list_from_base_ref(
    tmp_path: pathlib.Path,
) -> None:
    """Behavioural half of test_the_reviewable_check_does_not_read_an_attacker_influenced_ref:
    proves the URL actually built at runtime carries BASE_REF, not merely that
    the YAML env block claims it will."""
    _, calls = _run_reviewable_step(tmp_path, _TOML_ONE_GLOB, ["infra/config/secrets/prod.enc.yaml"])
    assert any("contents/.pr_agent.toml?ref=master" in c for c in calls), (
        f"the ignore list was not fetched from BASE_REF=master: {calls!r}"
    )


# --- the gate's half of the handoff (#1184) --------------------------------


def _gate_resolve_step() -> dict:
    """The gate step that turns an event into a PR number.

    Found by its `id:`, which every later step's `if:` already depends on,
    rather than by its name — a rename must not silently skip these.
    """
    steps = _load(GATE)["jobs"]["attestation"]["steps"]
    return next(s for s in steps if s.get("id") == "pr")


def test_the_gate_may_read_a_run_and_may_do_nothing_else_to_it() -> None:
    """`actions: read` is what makes the download possible, and its ceiling.

    Below it, the gate cannot list the reviewer run's artifacts and every
    `/review` resolves to nothing. Above it — `actions: write` — the gate could
    start, cancel or re-run the workflow whose output it judges, which is a
    judge holding the defendant's calendar.
    """
    permissions = _load(GATE)["permissions"]
    assert permissions.get("actions") == "read", (
        f"the gate's `actions:` permission is {permissions.get('actions')!r}. "
        f"`read` is required to list the reviewer run's artifacts, and it is "
        f"also the ceiling: a gate that can re-run what it judges is not a gate."
    )


def test_the_gate_downloads_the_artifact_under_the_name_the_reviewer_writes() -> None:
    """The reading half of the two-file agreement.

    Its sending half is asserted above. Until this existed the suite checked
    only that `pr-agent.yml` uploads under a name the suite itself declares —
    a sender agreeing with a fixture rather than with any consumer, which is
    lesson-357's failure class wearing a passing test.
    """
    run = _gate_resolve_step()["run"]
    assert f"/artifacts?name={ARTIFACT_NAME}" in run, (
        f"the gate does not query the reviewer run's artifacts by the name "
        f"{ARTIFACT_NAME!r}. The reviewer uploads under it; a gate looking for "
        f"anything else finds nothing, falls through, and reports every "
        f"`/review` as unreviewed — silently, which is the whole failure class."
    )


def test_the_handed_pr_number_is_preferred_over_the_inferred_one() -> None:
    """Route ORDER is the fix, not the mere presence of a route.

    On the `/review` path `commits/{head_sha}/pulls` asks about master's tip,
    and GitHub answers — with the pull request that was merged to produce it.
    Consulted first, that attests an already-merged PR and leaves the open one
    exactly as unreviewed as before. Only the artifact carries the number from
    the run being judged, so it goes first.
    """
    run = _gate_resolve_step()["run"]
    handed = run.find(f"/artifacts?name={ARTIFACT_NAME}")
    inferred = run.find("/commits/")
    assert handed >= 0 and inferred >= 0, "both resolution routes must be present"
    assert handed < inferred, (
        "the gate consults `commits/{head_sha}/pulls` before the artifact. On a "
        "comment-triggered run that head SHA is master's, so the inference wins "
        "and answers about the wrong pull request."
    )


# The five tests below EXECUTE the shipped script with `gh` stubbed, rather than
# reading it. That is not thoroughness for its own sake: `workflow_run` fires
# only from the default-branch copy of a workflow, so this half cannot run on
# the branch that introduces it and CI has no way to exercise it before merge.
# Written after lesson-361 — "CI green" is not the same claim as "this runs" —
# these are the claim CI could not otherwise make.
_GH_STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_CALLS"
case "$*" in
  *"/artifacts?name=pr-number"*) [ -n "${STUB_ARTIFACT_FAIL:-}" ] && exit 1
                          printf '%s' "${STUB_ARTIFACT_ID:-}" ;;
  *"/artifacts?name="*)   ;;
  *"/artifacts/"*"/zip"*) [ -n "${STUB_ZIP:-}" ] && cat "$STUB_ZIP" || exit 1 ;;
  *"/commits/"*"/pulls"*) printf '%s' "${STUB_SHA_PR:-}" ;;
  *"/pulls/"*)            printf '%s\\n' "deadbeef" ;;
  *) exit 1 ;;
esac
"""
# The stub answers as GITHUB does, not as the gate expects: a query for any
# other artifact name returns an empty list, exactly as the real API does for a
# run that uploaded nothing under it. So a name drifting on the reading side is
# caught behaviourally — the gate silently resolves the wrong PR — and not only
# by the string assertion above.


def _zip_holding(tmp_path: pathlib.Path, label: str, payload: str) -> str:
    """A stand-in for what `actions/upload-artifact` stores: one zipped file."""
    path = tmp_path / f"{label}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pr-number.txt", payload)
    return str(path)


def _run_resolve(tmp_path: pathlib.Path, **scenario: str) -> tuple[dict[str, str], list[str]]:
    """Run the resolve step as a `workflow_run` with no PR in its payload.

    Returns its `GITHUB_OUTPUT` and the log of API calls it actually made. The
    second is what makes route ORDER observable instead of merely declared.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "gh"
    stub.write_text(_GH_STUB, encoding="utf-8")
    stub.chmod(0o755)
    output = tmp_path / "github_output"
    output.touch()
    calls = tmp_path / "gh_calls"
    calls.touch()

    step = _gate_resolve_step()
    # Every env value the step declares as a LITERAL, taken from the workflow
    # rather than restated here. The `${{ ... }}` ones are the event's, and the
    # scenario supplies those below. Seeding from the file means a new literal
    # the step comes to depend on arrives here automatically, instead of this
    # harness passing while the real job fails on an unset variable.
    literal_env = {k: str(v) for k, v in (step.get("env") or {}).items() if "${{" not in str(v)}

    env = {
        **os.environ,
        **literal_env,
        # The interpreter's own directory too: the script calls `python`, which
        # `actions/setup-python` puts on PATH in the job and a bare `python3`
        # environment would not have. Absent it this fails for a reason that has
        # nothing to do with what is under test.
        "PATH": os.pathsep.join([str(bindir), str(pathlib.Path(sys.executable).parent), os.environ["PATH"]]),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "mlorentedev/kubelab",
        "GH_CALLS": str(calls),
        "GH_TOKEN": "stub",
        "EVENT": "workflow_run",
        "PR_FROM_EVENT": "",
        # Empty, and that is the whole defect: a comment has no head ref, so the
        # run is associated with the default branch and carries no pull requests.
        "RUN_PRS": "[]",
        "RUN_HEAD": "0" * 40,
        "RUN_ID": "999",
        "STUB_ARTIFACT_ID": "",
        "STUB_ARTIFACT_FAIL": "",
        "STUB_ZIP": "",
        "STUB_SHA_PR": "",
        **scenario,
    }
    proc = subprocess.run(  # noqa: S603
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"the resolve step exited {proc.returncode}. It must always exit 0 on a "
        f"resolution failure — the verdict is `skip`, not a broken job.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    parsed = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if "=" in line)
    return parsed, calls.read_text(encoding="utf-8").splitlines()


@_needs_bash
def test_a_review_comment_resolves_its_pr_from_the_artifact(tmp_path: pathlib.Path) -> None:
    """#1184's "Done when", executed: a run with no PR in its payload resolves.

    This is the case the gate has never handled. Before the artifact route it
    reached `commits/{master_sha}/pulls`, got an answer about the wrong pull
    request or none at all, and skipped.
    """
    out, calls = _run_resolve(
        tmp_path,
        STUB_ARTIFACT_ID="77",
        STUB_ZIP=_zip_holding(tmp_path, "good", "1208"),
        STUB_SHA_PR="4242",
    )
    assert out["skip"] == "false"
    assert out["number"] == "1208", (
        f"resolved #{out['number']} rather than the #1208 the reviewer run handed "
        f"over. #4242 is what the SHA inference would have answered."
    )
    assert not [c for c in calls if "/commits/" in c], (
        "the inference ran anyway. A handed-over number must end the search — "
        "consulting the fallback after it is at best wasted, at worst a race "
        "between two answers about different pull requests."
    )


@_needs_bash
def test_a_reviewer_run_with_no_artifact_still_falls_through(tmp_path: pathlib.Path) -> None:
    """Absent is a legitimate state, not an error.

    A run cancelled while PENDING (#1203) executes no steps at all, so it
    uploads nothing — and `workflow_run: [completed]` fires for it regardless.
    `set -euo pipefail` is active in this script, so an unguarded call on the
    artifact route would end the job here instead of at the next route.
    """
    out, calls = _run_resolve(tmp_path, STUB_ARTIFACT_ID="", STUB_SHA_PR="4242")
    assert out["skip"] == "false"
    assert out["number"] == "4242", "the SHA route must still answer when no artifact exists"
    assert [c for c in calls if "/commits/" in c], "the fallback was never reached"


@_needs_bash
def test_a_failed_artifact_lookup_does_not_take_the_gate_down_with_it(
    tmp_path: pathlib.Path,
) -> None:
    """The call itself can fail, and the job must survive it.

    A 403 is the one to picture: drop `actions: read` from the gate's
    permissions and every artifact lookup returns one. Under `set -e` that ends
    the job before the SHA route, so a permission regression would stop being
    "the new route is inert" — today's behaviour, which is the bound this
    change promised — and become "the gate errors on every reviewer run".
    """
    out, calls = _run_resolve(tmp_path, STUB_ARTIFACT_FAIL="1", STUB_SHA_PR="4242")
    assert out["number"] == "4242", "a failed artifact lookup must fall through, not abort"
    assert [c for c in calls if "/commits/" in c], "the fallback was never reached"


@_needs_bash
def test_an_artifact_that_is_not_a_pr_number_demotes_rather_than_erupts(
    tmp_path: pathlib.Path,
) -> None:
    """The content is attacker-reachable, so it may not be trusted OR fatal.

    A fork PR controls `pr-agent.yml` on the `pull_request` path and can put
    anything in the artifact. Treating that as a broken assumption — the `exit
    1` the shared check does at the end — would let any PR fail this gate's job
    on unrelated runs. It is a bad input, so the route reports nothing found.
    """
    out, calls = _run_resolve(
        tmp_path,
        STUB_ARTIFACT_ID="77",
        STUB_ZIP=_zip_holding(tmp_path, "hostile", "; rm -rf /"),
        STUB_SHA_PR="4242",
    )
    assert out["skip"] == "false"
    assert out["number"] == "4242", "a hostile artifact must demote to the next route"
    assert [c for c in calls if "/commits/" in c], "the fallback was never reached"


@_needs_bash
def test_a_run_that_ties_to_nothing_skips_and_never_guesses(tmp_path: pathlib.Path) -> None:
    """The terminal state, and the invariant the whole change is bounded by.

    Every route ends here rather than in a recovery that invents a reference
    (mlorentedev/dotfiles#1128). A gate that guesses which PR a run belongs to
    publishes a verdict about a PR nobody looked at — a silently-broken gate
    traded for a silently-permissive one.
    """
    out, _ = _run_resolve(tmp_path, STUB_ARTIFACT_ID="", STUB_SHA_PR="")
    assert out == {"skip": "true"}, (
        f"a workflow_run that ties to no pull request produced {out!r}. It must "
        f"produce exactly `skip=true` — no number, and above all no status."
    )


# --- the reviewer's model policy, held in two files ------------------------


def _review_job() -> dict:
    """The job that actually runs the reviewer, found by the action it uses
    rather than by its key — a renamed job must not silently skip these."""
    jobs = _load(REVIEWER)["jobs"]
    return next(
        j for j in jobs.values() if any("pr-agent@" in str(step.get("uses", "")) for step in j.get("steps", []))
    )


def _fallback_model_names() -> set[str]:
    """Model NAMES from .pr_agent.toml's fallback chain, with the transport
    prefix stripped.

    The prefix differs between the two files by design and comparing full ids
    would make this guard either vacuous or permanently red: the toml says
    `openai/mimo-v2.6-flash` because LiteLLM reaches NaN over the OpenAI-compatible
    transport, while the pool says `nan/mimo-v2.6-flash` because that is the provider
    a reviewer records. Same model, two namespaces.
    """
    raw = re.search(r"^fallback_models\s*=\s*\[(.*?)\]", PR_AGENT_CONFIG.read_text(encoding="utf-8"), re.M | re.S)
    assert raw, "fallback_models not found in .pr_agent.toml"
    return {m.split("/")[-1] for m in re.findall(r'"([^"]+)"', raw.group(1))}


def _primary_model_name() -> str:
    """The model PR-Agent actually reviews with, transport prefix stripped."""
    m = re.search(r'^model\s*=\s*"([^"]+)"', PR_AGENT_CONFIG.read_text(encoding="utf-8"), re.M)
    assert m, "model not found in .pr_agent.toml"
    return m.group(1).split("/")[-1]


def test_every_model_pr_agent_reviews_with_is_admitted_in_the_reviewer_pool() -> None:
    """`.pr_agent.toml` says who may review a PR; `harness/reviewer-pool.json`
    says who may sign a spec review. The toml's own comment names the failure
    this prevents — "two files in one repo holding opposing views on who may
    review is its own defect" — and it was held by hand until now.

    The PRIMARY is checked, not only the chain behind it. Covering fallbacks
    alone left the model that actually runs unasserted: changing `model` to a
    flash tier the pool explicitly rejects would have passed every test while
    the reviewer ran a vetoed model — the exact failure this guard exists to
    prevent, reachable through the one line it did not read.
    """
    # Matched on each member's `pr_agent.model` (TOOL-082), not on the id: a
    # member admitted for the adversarial review is not thereby a CI reviewer.
    admitted = {
        e["pr_agent"]["model"].split("/")[-1]
        for e in json.loads(REVIEWER_POOL.read_text(encoding="utf-8"))["pool"]
        if "pr_agent" in e
    }
    for model in {_primary_model_name()} | _fallback_model_names():
        assert model in admitted, (
            f"{model!r} is a model PR-Agent reviews with but is not in the reviewer "
            "pool. Admit it there with its evaluation, or drop it from the config — "
            "the two files must not disagree about who may review."
        )


def test_a_comment_only_triggers_the_reviewer_when_it_is_a_slash_command() -> None:
    """Without this, any comment by a collaborator starts a review — including
    the reviewer's own triage tables and ordinary conversation, each of which
    spends an inference slot the next real review needs."""
    condition = " ".join(str(_review_job()["if"]).split())
    assert "startsWith(github.event.comment.body, '/')" in condition, (
        "the issue_comment path is not filtered to slash commands"
    )
    # The other half of the same condition, and the one with teeth. This job
    # holds NAN_API_KEY and pull-requests: write on a PUBLIC repository, so
    # without the association check any account that can comment could start
    # it. The guard is in the workflow; until now only the slash half was
    # asserted, so deleting this line left every test green.
    assert (
        'contains(fromJSON(\'["OWNER","MEMBER","COLLABORATOR"]\'), github.event.comment.author_association)'
    ) in condition, "the issue_comment path is not restricted to repository members"


class _Null:
    """Actions' null: falsy, formats as '', and a property of null is null.

    `github.event.pull_request.number` on an `issue_comment` run is null in
    Actions, not an error, and the group key relies on that to fall through to
    `github.event.issue.number`.
    """

    def __bool__(self) -> bool:
        return False

    def __getattr__(self, name: str) -> "_Null":
        return self

    def __str__(self) -> str:
        return ""

    def __eq__(self, other: object) -> bool:
        return other is None or isinstance(other, _Null)

    def __hash__(self) -> int:
        return 0


_NULL = _Null()


class _Ctx(dict):
    """A GitHub expression context: attribute access, and absent keys are null."""

    def __getattr__(self, name: str) -> object:
        return self.get(name, _NULL)


def _ctx(value: object) -> object:
    return _Ctx({k: _ctx(v) for k, v in value.items()}) if isinstance(value, dict) else value


def _to_python_operators(code: str) -> str:
    """Rewrite the operators and literals of an expression fragment that holds no
    string literal. String literals are kept apart, so `== 'true'` compares with
    the string Actions compares with, not with Python's `True`."""
    code = code.replace("&&", " and ").replace("||", " or ")
    code = re.sub(r"!(?!=)", " not ", code)
    return re.sub(r"\bfalse\b", "False", re.sub(r"\btrue\b", "True", code))


def _evaluate(expression: str, github: dict, steps: dict | None = None) -> object:
    """Evaluate a GitHub Actions expression over `github`, the way Actions does.

    The subset this workflow uses maps onto Python with the same value
    semantics: `&&` and `||` return an operand, not a boolean, and '', 0, null
    and false are the falsy values in both languages. `steps` is the step
    context a step-level `if:` reads; `always()` is true for a step that is
    reached at all.
    """
    python = "".join(
        part if part.startswith("'") else _to_python_operators(part)
        for part in re.split(r"('[^']*')", expression.strip().removeprefix("${{").removesuffix("}}"))
    )
    names = {
        "github": _ctx(github),
        "steps": _ctx(steps or {}),
        "always": lambda: True,
        "format": lambda template, *args: re.sub(r"\{(\d+)\}", lambda m: str(args[int(m.group(1))]), template),
        "startsWith": lambda text, prefix: str(text or "").lower().startswith(prefix.lower()),
        "contains": lambda haystack, needle: needle in (haystack or ""),
        "fromJSON": json.loads,
    }
    return eval(" ".join(python.split()), {"__builtins__": {}}, names)  # noqa: S307 -- repository's own workflow


def _pull_request_run(*, draft: bool, actor: str) -> dict:
    """One `pull_request` run on one PR. Only what can change between its runs varies."""
    return {
        "workflow": "PR-Agent",
        "event_name": "pull_request",
        "actor": actor,
        "head_ref": "fix/something",
        "event": {"pull_request": {"number": 7, "draft": draft, "head": {"repo": {"fork": False}}}},
    }


def _comment_run(*, body: str, association: str) -> dict:
    """One `issue_comment` run on the same PR. The comment's body and author vary per comment."""
    return {
        "workflow": "PR-Agent",
        "event_name": "issue_comment",
        "actor": "someone",
        "head_ref": "",
        "event": {
            "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/7"}},
            "comment": {"body": body, "author_association": association},
        },
    }


def test_a_run_the_job_skips_cannot_cancel_one_that_reviews() -> None:
    """No run the job skips may share a concurrency group with a run it reviews (#1944).

    The per-PR group cancels in progress, and a run joins it before the job's
    `if:` is read. So a run carrying a draft payload, which the job skips,
    cancelled the `ready_for_review` run in the same group: measured on #1942,
    `cancelled` plus `skipped`, and no review. Any skip condition that can
    change between two runs of one PR has the same shape: draft state, and the
    actor, since a human's push to a Dependabot PR is reviewed and the bot's
    rebase after it is not. Fork and branch prefix are fixed for a PR's life.
    Comment runs have it too (#1950): every comment starts a run, and only a
    member's slash command is reviewed, so a triage comment or a stranger's
    comment would cancel a `/review` in flight.

    Both expressions are evaluated rather than searched for a token, so a group
    key that mentions a condition without separating its two states fails here.
    """
    workflow = _load(REVIEWER)
    job_if = str(workflow["jobs"]["review"]["if"])
    group = str(workflow["concurrency"]["group"])
    runs = [
        _pull_request_run(draft=draft, actor=actor)
        for draft in (False, True)
        for actor in ("a-maintainer", "dependabot[bot]")
    ] + [
        _comment_run(body=body, association=association)
        for body in ("/review", "## Review triage")
        for association in ("MEMBER", "NONE")
    ]
    reviewed = {_evaluate(group, run) for run in runs if _evaluate(job_if, run)}
    skipped = {_evaluate(group, run) for run in runs if not _evaluate(job_if, run)}
    assert reviewed and skipped, "every run reviews, or none does: the fixture no longer exercises the job's if:"
    assert not reviewed & skipped, f"a skipped run shares a group with a reviewing one: {sorted(reviewed & skipped)}"


# --- the reviewer's time and findings budget, held in two files -------------


def _attempts() -> dict[str, dict]:
    """Every PR-Agent attempt, by step id, in execution order (TOOL-082)."""
    return {s["id"]: s for s in _review_job()["steps"] if "pr-agent@" in str(s.get("uses", ""))}


def _nan_attempt() -> dict:
    """The NaN attempt, found by its id: the job now runs the action three times."""
    return _attempts()["pr_agent"]


def _review_env() -> dict:
    return _nan_attempt().get("env", {})


def _preflight_env() -> dict:
    return next(s for s in _review_job()["steps"] if s.get("id") == "models")["env"]


def _toml() -> dict:
    import tomllib

    return tomllib.loads(PR_AGENT_CONFIG.read_text(encoding="utf-8"))


def test_a_failed_call_is_not_replayed_before_the_next_model_runs() -> None:
    """PR-Agent 0.46.0 replays a failed call at two layers before it consults the
    fallback: the handler's `MODEL_RETRIES = 2` (timeouts included while
    `retry_same_model_on_timeout` is true) times the completion client's default
    retries. Run 36800846902, one of #1909's 720 s failures: mimo-v2.5 answered
    401 at once, then deepseek took 2 x 3 x 120 s. With both settings off a
    timed-out call goes straight to the next model. A non-timeout `APIError` is
    still replayed once: `_should_retry_same_model` has no setting for it, and
    the step limit asserted below is what bounds that case.

    Asserted in BOTH files: PR-Agent reads `.pr_agent.toml` from the default
    branch, the workflow from the PR head, so only the env value reaches the PR
    that changes it, and the toml value is what every later PR inherits.
    """
    config = _toml()["config"]
    env = _review_env()
    assert config.get("retry_same_model_on_timeout") is False
    assert str(env.get("CONFIG__RETRY_SAME_MODEL_ON_TIMEOUT")).lower() == "false"
    assert config.get("num_retries") == 0
    assert str(env.get("CONFIG__NUM_RETRIES")) == "0"


def test_every_request_to_nan_is_streamed() -> None:
    """NaN sits behind Cloudflare, which answers 524 to a request that sends no
    bytes for about 125 s. A review takes mimo-v2.6-flash longer: #1962's own
    prompt, sent directly, returned 524 at 126 s unstreamed and 200 at 275 s
    streamed. Upstream forces streaming only when BOTH the declared provider and
    an api_base substring match, so all three keys must agree with the base URL
    the workflow sends, in both files.
    """
    litellm = _toml()["litellm"]
    env = _review_env()
    host = env["OPENAI__API_BASE"].split("//", 1)[1].split("/", 1)[0]
    assert litellm["custom_llm_provider"] == litellm["force_streaming_custom_llm_provider"] == "openai"
    assert any(s in host for s in litellm["force_streaming_api_base_substrings"])
    assert env["LITELLM__CUSTOM_LLM_PROVIDER"] == litellm["custom_llm_provider"]
    assert env["LITELLM__FORCE_STREAMING_CUSTOM_LLM_PROVIDER"] == litellm["force_streaming_custom_llm_provider"]
    assert (
        json.loads(env["LITELLM__FORCE_STREAMING_API_BASE_SUBSTRINGS"])
        == litellm["force_streaming_api_base_substrings"]
    )
    # Only NaN is reached through the OpenAI transport. On an Anthropic attempt
    # NaN's keys would send a Claude model to NaN's base URL, and the toml's
    # provider, read from the default branch, applies to every model unless the
    # attempt overrides it: #2302's first Sonnet run was refused by the OpenAI
    # transport while this test asserted only that no key leaked.
    for step_id in ANTHROPIC_ATTEMPTS:
        env = _attempts()[step_id]["env"]
        leaked = [k for k in env if k.startswith(("LITELLM__", "OPENAI__")) and k != "LITELLM__CUSTOM_LLM_PROVIDER"]
        assert not leaked, f"{step_id} carries {leaked}"
        assert env.get("LITELLM__CUSTOM_LLM_PROVIDER") == "anthropic", f"{step_id} inherits the toml's provider"


def test_a_review_can_report_more_findings_than_the_upstream_default() -> None:
    """PR-Agent 0.46.0 marks a review `complete` only when it reports FEWER
    findings than `num_max_findings` (`allow_resolution` in `pr_reviewer.py`):
    at the cap, there may be more it did not say. At the default of 3, any review
    with three findings is partial by construction, and the merge rule requires a
    complete one. #1955 hit it on two heads in a row with three real findings each.
    """
    assert int(_toml()["pr_reviewer"]["num_max_findings"]) > 3
    assert int(_review_env()["PR_REVIEWER__NUM_MAX_FINDINGS"]) == int(_toml()["pr_reviewer"]["num_max_findings"])


def test_every_model_in_the_chain_gets_its_whole_timeout_inside_the_job() -> None:
    """Two bounds, because the pinned handler gives a model two shapes of worst case.

    A timed-out call is not replayed, so the healthy chain costs one `ai_timeout`
    per model and must fit inside the PR-Agent step's own limit. The timeout
    itself must exceed what a streamed review takes: 275-300 s for #1962's
    30k-token diff on mimo-v2.6-flash. Upstream's 120 s timed out on both models
    in run 36803951714.

    A non-timeout `APIError` (a 5xx, a dropped stream) is replayed once on the
    same model: `MODEL_RETRIES = 2` at litellm_ai_handler.py:141 in the pinned
    v0.46.0, with no setting. That costs up to 2 x 2 x `ai_timeout`, more than the
    job's 15 min. The step limit cuts it, and must leave the job time for the
    step after it to name the failure: a cancelled job publishes nothing and
    names nothing, which is #1909, and its AC2 asks for a named failure in under
    15 min. The 60 s is setup and that step, measured at about 45 s on #1962.

    Inside the step, PR-Agent works 11-13 s before its first request (config,
    diff, prompt; runs 36806561401, 36807143031, 36807944435), so the chain gets
    the step minus a 60 s slack. With streaming, `ai_timeout` is the HTTP
    client's per-read timeout, not a total: run 36807143031's answer arrived
    360 s after its request. The step limit is the only total bound.
    """
    timeout = int(_toml()["config"]["ai_timeout"])
    assert str(_review_env()["CONFIG__AI_TIMEOUT"]) == str(timeout)
    # The chain the job runs is the preflight's, handed on by the draw; count it
    # from the toml only after proving the two agree.
    assert json.loads(_preflight_env()["DECLARED_FALLBACK_MODELS"]) == _toml()["config"]["fallback_models"]
    chain = 1 + len(_fallback_model_names())
    assert timeout > 300
    step = _nan_attempt()
    assert "timeout-minutes" in step, "the PR-Agent step has no limit of its own; a replayed APIError outlives the job"
    step_seconds = int(step["timeout-minutes"]) * 60
    assert chain * timeout + 60 <= step_seconds
    assert step_seconds + 60 < int(_review_job()["timeout-minutes"]) * 60
    # Time left after the cut names nothing unless the naming step runs after a
    # failed step; the default `success()` would skip it.
    naming = next(s for s in _review_job()["steps"] if s.get("name") == "Fail if no review was published")
    assert "always()" in str(naming.get("if", ""))


def test_the_workflow_reviews_with_the_toml_model() -> None:
    """The env reaches the PR under test, the toml every later default-branch
    read. Two models in two files is how mimo-v2.5's retirement produced a 401
    on one path and not the other (#1909). Since TOOL-082 the workflow declares
    the chain on the preflight, and the NaN attempt takes what the draw hands on."""
    assert _preflight_env()["DECLARED_MODEL"] == _toml()["config"]["model"]
    assert _review_env()["CONFIG__MODEL"] == "${{ steps.route.outputs.nan_model }}"
    assert _review_env()["CONFIG__FALLBACK_MODELS"] == "${{ steps.route.outputs.nan_fallbacks }}"


_OPEN_GH_STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_CALLS"
[ "$STUB_STATE" = "fail" ] && exit 1
echo "$STUB_STATE"
"""
# Answers as `gh api ... --jq` would: the filtered state, already a word.


def _run_open_step(tmp_path: pathlib.Path, state: str) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "gh"
    stub.write_text(_OPEN_GH_STUB, encoding="utf-8")
    stub.chmod(0o755)
    output = tmp_path / "github_output"
    output.touch()
    env = {
        **os.environ,
        "PATH": os.pathsep.join([str(bindir), os.environ["PATH"]]),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "mlorentedev/kubelab",
        "GH_CALLS": str(tmp_path / "gh_calls"),
        "GH_TOKEN": "stub",
        "PR_NUMBER": "2179",
        "STUB_STATE": state,
    }
    step = _reviewer_step("Skip a review whose PR is no longer open")
    proc = subprocess.run(  # noqa: S603
        ["bash", "-c", step["run"]], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if "=" in line)


@_needs_bash
@pytest.mark.parametrize(
    ("state", "gone"), [("merged", "true"), ("closed", "true"), ("draft", "true"), ("open", None), ("fail", None)]
)
def test_a_queued_review_of_a_pr_that_is_no_longer_open_is_dropped(
    tmp_path: pathlib.Path, state: str, gone: str | None
) -> None:
    """A run waits in the queue with the event it was queued with. Only a
    definite answer drops it: a failed read reviews, as before the queue."""
    assert _run_open_step(tmp_path, state).get("gone") == gone


@pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq to evaluate the step's filter")
@pytest.mark.parametrize(
    ("pull", "state"),
    [
        ({"merged": True, "state": "closed", "draft": False}, "merged"),
        ({"merged": False, "state": "closed", "draft": False}, "closed"),
        ({"merged": False, "state": "open", "draft": True}, "draft"),
        ({"merged": False, "state": "open", "draft": False}, "open"),
    ],
)
def test_the_state_filter_reads_the_pull_request(pull: dict, state: str) -> None:
    """The filter `gh api --jq` applies, run over the fields the API returns."""
    run = _reviewer_step("Skip a review whose PR is no longer open")["run"]
    jq_filter = re.search(r"--jq '([^']+)'", run).group(1)
    proc = subprocess.run(  # noqa: S603
        ["jq", "-r", jq_filter], input=json.dumps(pull), capture_output=True, text=True, check=True
    )
    assert proc.stdout.strip() == state


def test_a_dropped_review_skips_everything_the_diff_check_gates() -> None:
    """The open-check only works through `reviewable`: an unrun step leaves its
    `any` output empty, and every later step tests that output."""
    steps = _review_steps()
    names = [s.get("name", "") for s in steps]
    assert names.index("Skip a review whose PR is no longer open") < names.index(
        "Determine whether the diff has anything to review"
    )
    condition = _reviewer_step("Determine whether the diff has anything to review")["if"]
    run = _pull_request_run(draft=False, actor="someone")
    assert not _evaluate(condition, run, {"open": {"outputs": {"gone": "true"}}})
    assert _evaluate(condition, run, {"open": {"outputs": {}}})
    # A slash command never runs the open-check and is still reviewed.
    assert _evaluate(condition, _comment_run(body="/review", association="OWNER"), {})


# Steps after the diff check that run whatever it decided, because they decide
# nothing: a timestamp is harmless on a dropped run.
UNGATED_AFTER_THE_DIFF_CHECK = {"Stamp run start"}


def test_every_step_after_the_diff_check_tests_its_output() -> None:
    """A dropped review leaves `any` empty, so a step runs only if it says otherwise.

    Each gated condition compares `any` with a literal `'true'` or `'false'`,
    and an empty output matches neither.
    """
    steps = _review_steps()
    names = [s.get("name", "") for s in steps]
    after = steps[names.index("Determine whether the diff has anything to review") + 1 :]
    assert after, "no step follows the diff check; the guard measures nothing"
    for step in after:
        if step.get("name") in UNGATED_AFTER_THE_DIFF_CHECK:
            continue
        condition = " ".join(str(step.get("if", "")).split())
        assert re.search(r"steps\.reviewable\.outputs\.any == '(true|false)'", condition), step.get("name")


# --- the review pool: preflight, draw, two providers (TOOL-082, #1843) ------

ANTHROPIC_ATTEMPTS = ("pr_agent_anthropic_first", "pr_agent_anthropic_second")
# What a reviewer reads: every attempt must review the same way, whichever
# provider the draw picked, or the draw would change the review, not the model.
REVIEW_SETTINGS = (
    "PR_REVIEWER__NUM_MAX_FINDINGS",
    "CONFIG__PUBLISH_OUTPUT_PROGRESS",
    "CONFIG__OUTPUT_RUN_DETAILS",
    "CONFIG__AI_TIMEOUT",
    "CONFIG__RETRY_SAME_MODEL_ON_TIMEOUT",
    "CONFIG__NUM_RETRIES",
)


def _step_by_id(step_id: str) -> dict:
    return next(s for s in _review_job()["steps"] if s.get("id") == step_id)


def _allowed_anthropic() -> set[str]:
    m = re.search(r'^ALLOWED_ANTHROPIC="([^"]+)"', ROUTE.read_text(encoding="utf-8"), re.M)
    assert m, "ALLOWED_ANTHROPIC not found in scripts/pr-agent-route.sh"
    return set(m.group(1).split())


def test_the_attempts_run_in_the_order_the_guard_reads_them() -> None:
    assert list(_attempts()) == ["pr_agent_anthropic_first", "pr_agent", "pr_agent_anthropic_second"]
    attempts = _reviewer_step("no review was published")["env"]["ATTEMPTS"]
    order = [re.search(r"steps\.(\w+)\.outcome", line).group(1) for line in attempts.strip().splitlines()]
    assert order == list(_attempts())


def test_every_attempt_runs_the_same_pinned_action() -> None:
    assert len({s["uses"] for s in _attempts().values()}) == 1


def test_the_two_anthropic_attempts_are_one_step_written_twice() -> None:
    """Steps cannot be reordered at run time, so the Anthropic attempt appears
    before and after the NaN one. Anything that differs between the copies
    besides when they run is a review that depends on the draw's order."""
    first, second = (_attempts()[i] for i in ANTHROPIC_ATTEMPTS)
    for key in ("uses", "env", "timeout-minutes", "continue-on-error"):
        assert first[key] == second[key], key


def test_every_attempt_reviews_with_the_same_settings() -> None:
    envs = {step_id: step["env"] for step_id, step in _attempts().items()}
    for key in REVIEW_SETTINGS:
        values = {step_id: str(env.get(key)) for step_id, env in envs.items()}
        assert len(set(values.values())) == 1, f"{key} differs between attempts: {values}"
    configs = [{k: v for k, v in env.items() if k.startswith("github_action_config.")} for env in envs.values()]
    assert all(c == configs[0] for c in configs), "the github_action_config settings differ between attempts"
    assert all(env["CONFIG__OUTPUT_RUN_DETAILS"] == "true" for env in envs.values())


def test_each_attempt_holds_only_its_own_provider_s_key() -> None:
    nan = _review_env()
    assert "secrets.NAN_API_KEY" in nan["OPENAI__KEY"]
    assert "ANTHROPIC__KEY" not in nan
    for step_id in ANTHROPIC_ATTEMPTS:
        env = _attempts()[step_id]["env"]
        assert "secrets.PR_AGENT_ANTHROPIC_API_KEY" in env["ANTHROPIC__KEY"]
        assert not any("NAN_API_KEY" in str(v) for v in env.values()), step_id


def test_only_the_draw_and_the_anthropic_attempts_see_the_anthropic_key() -> None:
    holders = {
        s.get("id") or s.get("name")
        for s in _review_job()["steps"]
        if "PR_AGENT_ANTHROPIC_API_KEY" in str(s.get("env", {}))
    }
    assert holders == {"route", *ANTHROPIC_ATTEMPTS}


def test_a_missing_anthropic_key_does_not_fail_the_credential_check() -> None:
    """NaN alone is a working pool. Without the Anthropic key the draw names the
    remedy and reviews on NaN; failing the job here would turn a degraded review
    into none."""
    assert "ANTHROPIC" not in str(_step_by_id("credential"))


def test_a_second_attempt_runs_only_on_a_measured_absence() -> None:
    nan_if = " ".join(str(_nan_attempt()["if"]).split())
    assert "steps.published_after_anthropic.outputs.published == 'false'" in nan_if
    second_if = " ".join(str(_attempts()["pr_agent_anthropic_second"]["if"]).split())
    assert "steps.published_after_nan.outputs.published == 'false'" in second_if
    # Its own gate on the route, not only the probe's: nan-only (second == none)
    # must keep the Anthropic key's holder skipped even if the probe ever answered.
    assert "steps.route.outputs.second == 'anthropic'" in second_if
    for probe in ("published_after_anthropic", "published_after_nan"):
        step = _step_by_id(probe)
        assert step["run"].strip() == './scripts/pr-agent-publish-guard.sh --probe --output "$GITHUB_OUTPUT"'
        assert "default_branch" in step["env"]["BASE_REF"]
        assert "always()" not in str(step["if"]), "a cancelled run must not spend a second attempt"


def test_the_anthropic_models_the_workflow_configures_are_the_allowlist() -> None:
    """The Console cannot restrict a key to a model, so ALLOWED_ANTHROPIC is the
    allowlist. A model the pool names outside it fails the draw; a model the
    workflow configures outside it would run without its temperature and
    thinking settings."""
    allowed = _allowed_anthropic()
    assert allowed == {"anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5"}
    env = _attempts()["pr_agent_anthropic_first"]["env"]
    assert set(json.loads(env["CONFIG__CLAUDE_ADAPTIVE_THINKING_MODELS_OVERRIDE"])) == allowed
    assert allowed <= set(json.loads(env["CONFIG__NO_TEMPERATURE_MODELS"]))
    pool = json.loads(REVIEWER_POOL.read_text(encoding="utf-8"))["pool"]
    named = {m["pr_agent"]["model"] for m in pool if m.get("pr_agent", {}).get("model", "").startswith("anthropic/")}
    assert named == allowed


def test_the_scripts_are_checked_out_sparsely_and_without_credentials() -> None:
    step = _reviewer_step("Check out the reviewer's scripts")
    paths = set(step["with"]["sparse-checkout"].split())
    assert paths == {
        "harness/reviewer-pool.json",
        "scripts/pr-agent-model-preflight.sh",
        "scripts/pr-agent-route.sh",
        "scripts/pr-agent-publish-guard.sh",
    }
    assert step["with"]["persist-credentials"] is False
    assert "ref" not in step["with"], "the PR's merge ref is the default; any other ref is a choice to justify"
    for path in paths:
        assert (REPO_ROOT / path).is_file(), path


def test_the_draw_reads_the_pr_s_size_from_the_api_not_the_event() -> None:
    """An `issue_comment` event carries no size or labels, so a `/review` would
    never take the risk route if the draw read them from the event."""
    run = _step_by_id("route")["run"]
    assert 'gh api "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}"' in run
    assert ".additions + .deletions" in run
    env = str(_step_by_id("route").get("env", {}))
    assert "additions" not in env and "labels" not in env


def test_the_job_outlasts_its_worst_two_attempt_path() -> None:
    """At most two attempts run, one per provider. The job must hold the longer
    pair plus the preflight (one probe per declared model), the draw's two
    Anthropic probes, and a minute each for setup, the probe between attempts
    and the final guard, or a slow run is cancelled before the guard names it."""
    attempts = _attempts()
    anthropic = int(attempts["pr_agent_anthropic_first"]["timeout-minutes"]) * 60
    nan = int(attempts["pr_agent"]["timeout-minutes"]) * 60
    preflight = 90 * (1 + len(json.loads(_preflight_env()["DECLARED_FALLBACK_MODELS"])))
    draw = 2 * 30
    assert re.search(
        r"PREFLIGHT_TIMEOUT:-90\}", (REPO_ROOT / "scripts/pr-agent-model-preflight.sh").read_text(encoding="utf-8")
    )
    assert re.search(r"ROUTE_PROBE_TIMEOUT:-30\}", ROUTE.read_text(encoding="utf-8"))
    overhead = 3 * 60
    assert anthropic + nan + preflight + draw + overhead < int(_review_job()["timeout-minutes"]) * 60


# Highest price per million tokens (input, output) and the ceiling one review
# may cost, per allowed model. Haiku 5.5's rates are its rates above 100,000
# prompt tokens; Sonnet 5.5 has no price step. Ported from dotfiles'
# pr-agent-config.bats, where the owner set the ceilings (ADR-046 there).
ANTHROPIC_PRICES = {
    "anthropic/claude-haiku-5-5": (0.50, 2.50, 0.25),
    "anthropic/claude-sonnet-5-5": (2.00, 10.00, 1.00),
}


def test_the_worst_anthropic_review_stays_under_its_ceiling() -> None:
    """The allowlist is a rule only because every allowed model needs a price
    row here, and its worst review under the caps must cost less than the
    ceiling. Claude's tokenizer counts about 30% more than PR-Agent's."""
    env = _attempts()["pr_agent_anthropic_first"]["env"]
    routed = "${{ steps.route.outputs.anthropic_model }}"
    assert env["CONFIG__MODEL"] == env["CONFIG__MODEL_WEAK"] == routed
    assert json.loads(env["CONFIG__FALLBACK_MODELS"]) == []
    prompt = int(env["CONFIG__MAX_MODEL_TOKENS"])
    assert (
        prompt == int(env["CONFIG__CUSTOM_MODEL_MAX_TOKENS"]) == int(_review_env()["CONFIG__CUSTOM_MODEL_MAX_TOKENS"])
    )
    output = int(env["DEFAULT_ANTHROPIC_CHAT_MAX_TOKENS"])
    for model in _allowed_anthropic():
        assert model in ANTHROPIC_PRICES, f"{model} is allowed but has no price row"
        price_in, price_out, ceiling = ANTHROPIC_PRICES[model]
        worst = prompt * 1.3 * price_in / 1e6 + output * price_out / 1e6
        assert worst < ceiling, f"{model}: worst review ${worst:.2f} exceeds ${ceiling:.2f}"
    # Not streamed, so ai_timeout bounds the whole answer and must end inside
    # the step, or the step's kill would hide PR-Agent's own timeout.
    assert int(env["CONFIG__AI_TIMEOUT"]) < int(_attempts()["pr_agent_anthropic_first"]["timeout-minutes"]) * 60
