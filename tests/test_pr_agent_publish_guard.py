"""TOOL-082 (#1843): scripts/pr-agent-publish-guard.sh decides whether THIS run published a review.

One definition of "published" for two callers in the pr-agent workflow: the
`--probe` between the first attempt and the second, which only a measured `false`
lets run, and the final guard, which fails the job when nothing was published.
Ported from mlorentedev/dotfiles, where a read timeout on the reviewer registry
once became an empty marker list and failed a reviewed PR with the wrong
diagnosis ("no review marker declared", mlorentedev/dotfiles#2069).

These run the REAL script against a stub `gh` whose every answer is set per test.
The guard script's behaviour is pinned here; how the workflow calls it is
tests/test_pr_agent_workflow.py's.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "scripts" / "pr-agent-publish-guard.sh"

pytestmark = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("bash", "jq")),
    reason="the guard needs bash and jq",
)

# Answers `gh api PATH ...` from STUB_<KEY>, where KEY is the call's subject:
# BASE / HEAD (the registry at each ref), PULL, COMMENTS. A value is either
# "fail:<code>" (always fails), "flaky:<code>" (fails on the first call only)
# or the response itself. Every call is logged to $CALLS.
FAKE_GH = r"""#!/usr/bin/env bash
api_path="$2"
case "$api_path" in
    *contents/harness/review-attestation.json?ref=main) key=BASE ;;
    *contents/harness/review-attestation.json?ref=*) key=HEAD ;;
    */pulls/*) key=PULL ;;
    */comments) key=COMMENTS ;;
    *) echo "stub gh: unexpected call: $*" >&2; exit 99 ;;
esac
echo "$key" >> "$CALLS"
eval "answer=\${STUB_$key:-}"
fail() {
    echo '{"message":"stub failure body"}'
    case "$1" in
        404) echo "gh: Not Found (HTTP 404)" >&2 ;;
        *) echo "gh: Gateway Timeout (HTTP $1)" >&2 ;;
    esac
    exit 1
}
case "$answer" in
    fail:*) fail "${answer#fail:}" ;;
    flaky:*)
        if [ "$(grep -c "^$key\$" "$CALLS")" -eq 1 ]; then fail "${answer#flaky:}"; fi
        answer=$(eval "printf '%s' \"\${STUB_${key}_OK}\"")
        ;;
esac
printf '%s\n' "$answer"
"""


def _registry(entries: list[dict[str, object]]) -> str:
    return base64.b64encode(json.dumps({"reviewers": entries}).encode()).decode()


REGISTRY = _registry([{"login": "github-actions", "review_markers": ["PR Reviewer Guide"]}])
NO_ENTRY = _registry([{"login": "coderabbitai[bot]", "review_markers": ["Walkthrough"]}])


def _comments(updated_at: str) -> str:
    return json.dumps(
        [{"user": {"login": "github-actions[bot]"}, "updated_at": updated_at, "body": "## PR Reviewer Guide"}]
    )


REVIEW = _comments("2026-10-07T10:00:00Z")
STARTED = "2026-10-07T09:00:00Z"


def attempts(first: str, second: str, third: str) -> str:
    """The workflow's ATTEMPTS, in execution order: Anthropic first (model `hk`),
    NaN (model `m`), Anthropic second. Each argument is that attempt's outcome."""
    return f"{first} hk\n{second} m\n{third} hk"


LEAKY = (
    "ATTEMPTS",
    "ROUTE_NOTE",
    "ROUTE_OUTCOME",
    "HEAD_SHA",
    "GH_TOKEN",
    "GITHUB_REPOSITORY",
    "PR_NUMBER",
    "BASE_REF",
    "STARTED",
)


class Guard:
    """The guard run as the workflow does, with the final guard's env."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls = tmp_path / "calls"
        self.calls.write_text("", encoding="utf-8")
        bindir = tmp_path / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if k not in LEAKY and not k.startswith("STUB_")}
        self.env.update(
            PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
            CALLS=str(self.calls),
            GUARD_RETRY_SECONDS="0",
            GITHUB_REPOSITORY="o/r",
            PR_NUMBER="7",
            BASE_REF="main",
            STARTED=STARTED,
            HEAD_SHA="abc123",
            ATTEMPTS=attempts("skipped", "success", "skipped"),
            ROUTE_NOTE="",
            ROUTE_OUTCOME="success",
        )

    def stub(self, **answers: str) -> None:
        """Set the stub gh's answers: STUB_BASE, STUB_COMMENTS and so on."""
        self.env.update({f"STUB_{key}": value for key, value in answers.items()})

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [str(GUARD), *args],
            env={**self.env, **env},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def probe(self) -> tuple[subprocess.CompletedProcess[str], str]:
        """Runs `--probe` and returns the process with the file it appended to."""
        out = self.tmp_path / "probe.out"
        out.write_text("", encoding="utf-8")
        proc = self.run("--probe", "--output", str(out))
        return proc, out.read_text(encoding="utf-8").strip()

    def calls_to(self, key: str) -> int:
        return self.calls.read_text(encoding="utf-8").splitlines().count(key)


@pytest.fixture
def guard(tmp_path: Path) -> Guard:
    return Guard(tmp_path)


def _output(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


def test_a_registry_read_that_keeps_failing_is_reported_as_an_api_failure_not_a_missing_marker(guard: Guard) -> None:
    guard.stub(BASE="fail:504", HEAD="fail:504")
    proc = guard.run()
    out = _output(proc)
    assert proc.returncode == 1, out
    assert "the GitHub API failed while determining whether a review marker is declared" in out
    assert "review-attestation.json?ref=main" in out
    assert "HTTP 504" in out
    assert "no review marker declared" not in out
    assert guard.calls_to("BASE") == 3


def test_a_registry_read_that_fails_once_is_retried_and_the_answer_is_not_prefixed_by_the_failed_body(
    guard: Guard,
) -> None:
    guard.stub(BASE="flaky:502", BASE_OK=REGISTRY, COMMENTS=REVIEW)
    proc = guard.run()
    assert proc.returncode == 0, _output(proc)
    assert 'review published (markers: ["PR Reviewer Guide"])' in _output(proc)
    assert guard.calls_to("BASE") == 2


def test_a_registry_with_no_github_actions_entry_still_fails_with_the_existing_message(guard: Guard) -> None:
    guard.stub(BASE=NO_ENTRY, HEAD=NO_ENTRY)
    proc = guard.run()
    assert proc.returncode == 1, _output(proc)
    assert "no review marker declared for github-actions" in _output(proc)
    assert "GitHub API failed" not in _output(proc)


def test_a_404_is_an_answer_not_an_outage_no_retry_and_the_head_ref_fallback_still_applies(guard: Guard) -> None:
    guard.stub(BASE="fail:404", HEAD=REGISTRY, COMMENTS=REVIEW)
    proc = guard.run()
    assert proc.returncode == 0, _output(proc)
    assert "reviewer registry entry found only on the PR head" in _output(proc)
    assert guard.calls_to("BASE") == 1


def test_a_failed_head_sha_lookup_on_an_issue_comment_run_is_reported_as_an_api_failure(guard: Guard) -> None:
    guard.stub(BASE=NO_ENTRY, PULL="fail:503")
    proc = guard.run(HEAD_SHA="")
    out = _output(proc)
    assert proc.returncode == 1, out
    assert "the GitHub API failed while determining whether a review marker is declared" in out
    assert "pulls/7" in out
    assert "no review marker declared" not in out
    assert guard.calls_to("PULL") == 3


def test_a_comment_listing_that_keeps_failing_is_reported_as_an_api_failure_not_a_missing_review(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS="fail:500")
    proc = guard.run()
    assert proc.returncode == 1, _output(proc)
    assert "the GitHub API failed while listing the PR's comments" in _output(proc)
    assert "published no review" not in _output(proc)


def test_a_comment_listing_that_answers_404_is_reported_as_such_no_retry_no_empty_outage_report(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS="fail:404")
    proc = guard.run()
    assert proc.returncode == 1, _output(proc)
    assert "listing the PR's comments answered 404" in _output(proc)
    assert guard.calls_to("COMMENTS") == 1
    assert "GitHub API failed" not in _output(proc)


def test_with_every_call_answering_and_no_review_comment_the_published_no_review_diagnosis_stands(
    guard: Guard,
) -> None:
    """The NaN branch carries kubelab's own measured causes (saturation, an empty
    body on a 200, a diff that outlives the step timeout), not dotfiles' run ids."""
    guard.stub(BASE=REGISTRY, COMMENTS="[]")
    proc = guard.run()
    out = _output(proc)
    assert proc.returncode == 1, out
    assert "PR-Agent reported success but published no review" in out
    assert "Three causes are measured here" in out
    assert "NaN limits concurrency per MODEL" in out
    for issue in ("#1205", "#1966", "#1909"):
        assert issue in out


def test_an_anthropic_attempt_that_published_nothing_is_not_blamed_on_nan(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS="[]")
    proc = guard.run(ATTEMPTS="success anthropic/claude-haiku-5-5\nskipped m")
    out = _output(proc)
    assert proc.returncode == 1, out
    assert "PR-Agent reported success but published no review" in out
    assert "No cause is measured yet for the Anthropic attempt" in out
    assert "NaN" not in out


def test_the_published_review_names_the_attempt_that_produced_it(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS=REVIEW)
    proc = guard.run(ATTEMPTS=attempts("skipped", "failure", "success"))
    assert proc.returncode == 0, _output(proc)
    assert "on hk" in _output(proc)


# --- probe: the gate in front of the second attempt ------------------------------


def test_probe_a_review_published_by_this_run_answers_true(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS=REVIEW)
    proc, answer = guard.probe()
    assert proc.returncode == 0, _output(proc)
    assert answer == "published=true"


def test_probe_no_review_answers_false_the_only_answer_that_runs_a_second_attempt(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS="[]")
    proc, answer = guard.probe()
    assert proc.returncode == 0, _output(proc)
    assert answer == "published=false"


def test_probe_a_review_older_than_this_runs_start_is_not_this_runs_review(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS=_comments("2026-10-07T08:00:00Z"))
    _, answer = guard.probe()
    assert answer == "published=false"


def test_probe_an_api_that_keeps_failing_answers_unknown_never_false(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS="fail:502")
    proc, answer = guard.probe()
    assert proc.returncode == 0, _output(proc)
    assert answer == "published=unknown"
    assert "HTTP 502" in _output(proc)


def test_probe_no_declared_marker_answers_unknown_never_false(guard: Guard) -> None:
    guard.stub(BASE=NO_ENTRY, HEAD=NO_ENTRY)
    _, answer = guard.probe()
    assert answer == "published=unknown"


def test_probe_a_comment_listing_that_is_not_json_answers_unknown_never_false(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS="<html>bad gateway</html>")
    _, answer = guard.probe()
    assert answer == "published=unknown"


def test_probe_a_pasted_heading_from_anyone_but_the_bot_is_not_a_review(guard: Guard) -> None:
    """Only github-actions[bot] publishes PR-Agent's review, so a human or another
    bot quoting the heading must not open the gate as if the run had reviewed."""
    pasted = json.dumps(
        [{"user": {"login": "someone"}, "updated_at": "2026-10-07T10:00:00Z", "body": "## PR Reviewer Guide"}]
    )
    guard.stub(BASE=REGISTRY, COMMENTS=pasted)
    _, answer = guard.probe()
    assert answer == "published=false"


def test_probe_on_the_head_fallback_a_bot_comment_without_the_heading_is_not_a_review(guard: Guard) -> None:
    """The head-ref fallback uses the generic heading, never a head-supplied marker
    (CWE-345), so a bot comment that lacks it still answers false."""
    other = json.dumps(
        [
            {
                "user": {"login": "github-actions[bot]"},
                "updated_at": "2026-10-07T10:00:00Z",
                "body": "## PR Code Suggestions",
            }
        ]
    )
    guard.stub(BASE="fail:404", HEAD=REGISTRY, COMMENTS=other)
    _, answer = guard.probe()
    assert answer == "published=false"


# --- final guard: the last attempt that ran is the one judged --------------------


def test_a_failed_second_attempt_is_reported_with_its_own_model_not_the_first_ones(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS="[]")
    proc = guard.run(ATTEMPTS=attempts("skipped", "failure", "failure"))
    assert proc.returncode == 1, _output(proc)
    assert "PR-Agent ended failure on hk" in _output(proc)


def test_anthropic_drawn_first_then_nan_the_nan_attempt_is_the_one_judged(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS="[]")
    proc = guard.run(ATTEMPTS=attempts("failure", "cancelled", "skipped"))
    assert proc.returncode == 1, _output(proc)
    assert "PR-Agent ended cancelled on m" in _output(proc)


def test_anthropic_drawn_first_and_alone_its_outcome_is_the_one_judged(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS=REVIEW)
    proc = guard.run(ATTEMPTS=attempts("success", "skipped", "skipped"))
    assert proc.returncode == 0, _output(proc)
    assert "on hk" in _output(proc)


def test_a_failure_with_no_second_attempt_repeats_why_a_member_was_out_of_the_draw(guard: Guard) -> None:
    proc = guard.run(
        ATTEMPTS=attempts("skipped", "failure", "skipped"), ROUTE_NOTE="PR_AGENT_ANTHROPIC_API_KEY is not set"
    )
    assert proc.returncode == 1, _output(proc)
    assert "PR-Agent ended failure on m" in _output(proc)
    assert "PR_AGENT_ANTHROPIC_API_KEY is not set" in _output(proc)


def test_no_attempt_at_all_no_pool_member_answered_fails_and_says_so(guard: Guard) -> None:
    proc = guard.run(ATTEMPTS=attempts("skipped", "skipped", "skipped"))
    assert proc.returncode == 1, _output(proc)
    assert "no review attempt ran" in _output(proc)
    assert "no member of the review pool answered" in _output(proc)


def test_no_attempt_because_the_draw_failed_names_the_draw_not_the_pool(guard: Guard) -> None:
    """A draw that exits non-zero (an unknown PR_AGENT_PROVIDER) writes no
    outputs, so every attempt reads skipped too; blaming the pool would send the
    reader to probe warnings that were never printed (mlorentedev/dotfiles#2188 review)."""
    proc = guard.run(ATTEMPTS=attempts("skipped", "skipped", "skipped"), ROUTE_OUTCOME="failure")
    assert proc.returncode == 1, _output(proc)
    assert "the draw itself failed" in _output(proc)
    assert "no member of the review pool answered" not in _output(proc)


def test_an_attempts_list_with_nothing_evaluated_is_no_attempt_not_a_success(guard: Guard) -> None:
    proc = guard.run(ATTEMPTS=" hk\n m\n hk")
    assert proc.returncode == 1, _output(proc)
    assert "no review attempt ran" in _output(proc)


def test_a_second_attempt_that_reviewed_after_a_first_failure_passes(guard: Guard) -> None:
    guard.stub(BASE=REGISTRY, COMMENTS=REVIEW)
    proc = guard.run(ATTEMPTS=attempts("skipped", "failure", "success"))
    assert proc.returncode == 0, _output(proc)
