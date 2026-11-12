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

Since CI-007 (mlorentedev/ci-workflows#33) `pr-agent.yml` is a caller of the
shared reviewer in mlorentedev/ci-workflows, pinned by SHA. The steps this file
used to pin (the publish guard, the reviewable check, the unreviewed declaration,
the queued lane, the preflight and the draw) are declared and tested there; a
`uses:` job has no steps to read. What stays here is what this repository owns:
the caller's inputs and concurrency key, the gate's half of every handoff, and
the `.pr_agent.toml` settings the shared NaN step does not override.
"""

from __future__ import annotations

import itertools
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


def _caller() -> dict:
    """The one job in pr-agent.yml: a call to the shared reviewer."""
    job = _load(REVIEWER)["jobs"]["review"]
    assert "uses" in job, "the review job no longer calls the shared workflow"
    return job


def _inputs() -> dict:
    return _caller().get("with", {})


SHARED_REVIEWER = re.compile(
    r"^    uses: mlorentedev/ci-workflows/\.github/workflows/pr-agent\.yml@([0-9a-f]{40}) # v\d+\.\d+\.\d+$",
    re.M,
)


def test_the_shared_reviewer_is_pinned_by_sha_not_by_tag() -> None:
    """A tag is mutable; the called job holds NAN_API_KEY on a public repository.

    Whoever can move the tag could change what runs with that credential, so the
    caller pins a full SHA with the tag beside it, the same rule this file held
    for every action the old job used.
    """
    assert SHARED_REVIEWER.search(REVIEWER.read_text(encoding="utf-8")), (
        "pr-agent.yml must call mlorentedev/ci-workflows' pr-agent.yml pinned by a full "
        "commit SHA with its tag in a comment"
    )


def test_the_reviewer_skips_release_deploy_and_promote_branches() -> None:
    """The branch skips moved from the job's `if:` to the shared job's input.

    Release PRs restate commits each reviewed when it landed. deploy/ and promote/
    carry generated version bumps (DELIVERY-004): two lines guaranteed against
    the generator by the config-drift gate, opened by `product-image-receiver.yml`
    and `promote-prod.yml`, and each would otherwise take the one running slot of
    the review lane from a human PR (#1203). All three are asserted, because
    dropping one leaves the others green.
    """
    prefixes = str(_inputs().get("skip_branch_prefixes", "")).replace(",", " ").split()
    for prefix in ("release-please--", "deploy/", "promote/"):
        assert prefix in prefixes, f"{prefix} is no longer skipped; those PRs would be reviewed again"


def test_an_ignored_only_pr_is_declared_unreviewed() -> None:
    """CI-GATE-017 (#1527): a diff wholly inside `.pr_agent.toml`'s [ignore] glob
    gives PR-Agent nothing to review. The shared job declares such a PR with the
    registry's escape label and section, and clears a stale label once the PR is
    reviewable again, only when the caller asks it to."""
    assert _inputs().get("declare_unreviewed") is True
    escape = json.loads((REPO_ROOT / "harness/review-attestation.json").read_text(encoding="utf-8"))["escape"]
    assert escape.get("label") and escape.get("section"), (
        "the shared job reads escape.label and escape.section from the registry; without them it cannot declare"
    )


def test_the_draw_reads_this_repository_s_pool() -> None:
    """ADR-070's weights and Anthropic members are this repository's, not the
    copy embedded in dotf, so the caller names its own pool."""
    pool = _inputs().get("pool")
    assert pool == "harness/reviewer-pool.json"
    assert (REPO_ROOT / pool).is_file()


def test_secrets_are_passed_by_name() -> None:
    assert set(_caller()["secrets"]) == {"NAN_API_KEY", "PR_AGENT_ANTHROPIC_API_KEY"}
    for name, value in _caller()["secrets"].items():
        assert value == f"${{{{ secrets.{name} }}}}", f"{name} is not passed through unchanged"


def test_the_caller_holds_no_more_than_the_shared_job_needs() -> None:
    """The workflow grants nothing; the job grants what the shared job declares."""
    workflow = _load(REVIEWER)
    assert workflow["permissions"] == {}
    assert _caller()["permissions"] == {"contents": "read", "pull-requests": "write", "issues": "write"}


def test_the_queue_is_not_beside_a_cancelling_group() -> None:
    """GitHub refuses `queue: max` in a group that cancels in progress, so the
    repository-wide queue lives on the shared job and this group keeps cancelling."""
    workflow = _load(REVIEWER)
    assert "queue" not in workflow["concurrency"]
    assert workflow["concurrency"]["cancel-in-progress"] is True

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


# The artifact carrying the PR number from the reviewer to the gate (#1184). The
# shared reviewer uploads it on comment runs, under this name, holding one file
# named `pr-number`.
# A literal, deliberately: the point of the assertions below is to anchor both
# workflows to a value neither of them derives. Reading the name out of
# `pr-agent.yml` and asserting the file agrees with itself would pass by
# construction -- the failure class lesson-357 catalogues.
ARTIFACT_NAME = "reviewed-pr"



_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="these steps are bash scripts")



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

    Its sending half is the shared reviewer's, in mlorentedev/ci-workflows,
    and is asserted there. Before CI-007 the suite checked only that
    `pr-agent.yml` uploads under a name the suite itself declares — a sender
    agreeing with a fixture rather than with any consumer, which is
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
  *"/artifacts?name=reviewed-pr"*) [ -n "${STUB_ARTIFACT_FAIL:-}" ] && exit 1
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
    """A stand-in for what the shared reviewer uploads: one zipped file, `pr-number`."""
    path = tmp_path / f"{label}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pr-number", payload)
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

def _declared_chain() -> list[str]:
    """The NaN chain the caller declares, in order, transport prefix included."""
    inputs = _inputs()
    return [inputs["declared_model"], *json.loads(inputs["declared_fallback_models"])]


def test_every_model_pr_agent_reviews_with_is_admitted_in_the_reviewer_pool() -> None:
    """The caller says which NaN models review a PR; `harness/reviewer-pool.json`
    says who may sign a spec review. Two files in one repo holding opposing views
    on who may review is its own defect, so the declared chain, primary included,
    must be admitted there (matched on each member's `pr_agent.model`, TOOL-082).

    The primary is checked, not only the chain behind it: covering fallbacks alone
    left the model that actually runs unasserted.
    """
    admitted = {
        e["pr_agent"]["model"]
        for e in json.loads(REVIEWER_POOL.read_text(encoding="utf-8"))["pool"]
        if "pr_agent" in e
    }
    chain = _declared_chain()
    assert chain[0] == "openai/mimo-v2.6-flash", "mimo leads: its failure is one the chain can move on from (#1205)"
    for model in chain:
        assert model in admitted, (
            f"{model!r} is a model PR-Agent reviews with but is not in the reviewer "
            "pool. Admit it there with its evaluation, or drop it from the caller."
        )


def test_the_toml_does_not_restate_what_the_shared_job_sets() -> None:
    """The shared job sets the model, the fallbacks, the model capacity and the
    LiteLLM transport by environment, which sits above `.pr_agent.toml`. It does
    not set the prompt cap `max_model_tokens` on the NaN step, so the toml keeps
    it (mlorentedev/ci-workflows#88): without it PR-Agent clips at 32000. A value
    restated here is silently overridden on the NaN step, and a `[litellm]`
    provider would also reach the Anthropic steps, which set none of their own:
    #2302's first Sonnet run was refused by the OpenAI transport for exactly that.
    """
    config = _toml()
    for key in ("model", "fallback_models", "custom_model_max_tokens"):
        assert key not in config["config"], f"[config] {key} is set by the shared workflow"
    assert "litellm" not in config, "a [litellm] provider would reach the shared Anthropic steps"
    assert "github_action_config" not in config

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
        "endsWith": lambda text, suffix: str(text or "").lower().endswith(suffix.lower()),
        "contains": lambda haystack, needle: needle in (haystack or ""),
        "fromJSON": json.loads,
    }
    return eval(" ".join(python.split()), {"__builtins__": {}}, names)  # noqa: S307 -- repository's own workflow


_RUN_IDS = itertools.count(1000)


def _pull_request_run(*, draft: bool, actor: str) -> dict:
    """One `pull_request` run on one PR. Only what can change between its runs varies."""
    return {
        "workflow": "PR-Agent",
        "event_name": "pull_request",
        "run_id": next(_RUN_IDS),
        "actor": actor,
        "head_ref": "fix/something",
        "event": {"pull_request": {"number": 7, "draft": draft, "head": {"repo": {"fork": False}}}},
    }


def _comment_run(*, body: str, association: str) -> dict:
    """One `issue_comment` run on the same PR. The comment's body and author vary per comment."""
    return {
        "workflow": "PR-Agent",
        "event_name": "issue_comment",
        "run_id": next(_RUN_IDS),
        "actor": "someone",
        "head_ref": "",
        "event": {
            "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/7"}},
            "comment": {"id": next(_RUN_IDS), "body": body, "author_association": association},
        },
    }


def test_a_run_the_job_skips_cannot_cancel_one_that_reviews() -> None:
    """No run the shared job skips may share a concurrency group with one it reviews (#1944, #1950).

    The per-PR group cancels in progress, and a run joins it before any job
    runs. Every comment starts a run and only a member's slash command is
    reviewed, so a triage comment or a stranger's would cancel a `/review` in
    flight; a bot push is ignored by the shared job, so a Dependabot rebase would
    cancel the review of a maintainer's push. Both get a group of their own.

    Draft state is no longer part of this. The shared job reads the PR's state
    live (`dotf pr reviewable`), so a run that joined the group with a stale
    draft payload reviews the PR as it is now instead of skipping it, which is
    the failure #1944 measured.

    The expression is evaluated rather than searched for a token, so a group key
    that mentions a condition without separating its two states fails here.
    """
    group = str(_load(REVIEWER)["concurrency"]["group"])
    reviewed = [
        _pull_request_run(draft=False, actor="a-maintainer"),
        _comment_run(body="/review", association="MEMBER"),
    ]
    skipped = [
        _pull_request_run(draft=False, actor="dependabot[bot]"),
        _comment_run(body="## Review triage", association="MEMBER"),
        _comment_run(body="/review", association="NONE"),
    ]
    reviewed_groups = {_evaluate(group, run) for run in reviewed}
    for run in skipped:
        assert _evaluate(group, run) not in reviewed_groups, f"a skipped run shares a group with a reviewing one: {run}"
    # And a newer /review from a member still supersedes an older one.
    assert len({_evaluate(group, _comment_run(body="/review", association="MEMBER")) for _ in range(2)}) == 1


def _toml() -> dict:
    import tomllib

    return tomllib.loads(PR_AGENT_CONFIG.read_text(encoding="utf-8"))



def test_a_failed_call_is_not_replayed_before_the_next_model_runs() -> None:
    """PR-Agent replays a failed call at two layers before it consults the
    fallback: the handler's `MODEL_RETRIES = 2` (timeouts included while
    `retry_same_model_on_timeout` is true) times the completion client's default
    retries. Run 36800846902, one of #1909's 720 s failures: mimo-v2.5 answered
    401 at once, then deepseek took 2 x 3 x 120 s. With both settings off a
    timed-out call goes straight to the next model.

    The shared NaN step sets `retry_same_model_on_timeout` by environment but not
    `num_retries`, so the toml value is the one that reaches it.
    """
    config = _toml()["config"]
    assert config.get("retry_same_model_on_timeout") is False
    assert config.get("num_retries") == 0


def test_a_review_can_report_more_findings_than_the_upstream_default() -> None:
    """PR-Agent marks a review `complete` only when it reports FEWER findings than
    `num_max_findings` (`allow_resolution` in `pr_reviewer.py`): at the cap, there
    may be more it did not say. At the default of 3, any review with three
    findings is partial by construction, and the merge rule requires a complete
    one. #1955 hit it on two heads in a row with three real findings each. The
    shared job does not set it, so the toml is what every review reads.
    """
    assert int(_toml()["pr_reviewer"]["num_max_findings"]) > 3


def test_a_streamed_review_gets_its_whole_timeout() -> None:
    """The timeout must exceed what a streamed review takes: 275-300 s for
    #1962's 30k-token diff on mimo-v2.6-flash. Upstream's 120 s timed out on both
    models in run 36803951714. The shared NaN step does not set `ai_timeout`, so
    the toml value is the one that applies there.
    """
    assert int(_toml()["config"]["ai_timeout"]) > 300
