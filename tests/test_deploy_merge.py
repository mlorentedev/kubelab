"""The merge step's judge: which open PRs it would merge or close (DELIVERY-004 AC6, #1619).

The judge is the merging actor's condition, so each condition it checks has a
test that breaks that condition alone and expects no merge. The merge itself is
one shell line in deploy-merge.yml, pinned by tests/test_deploy_shape_widening.py.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from tests.test_deploy_shape import HEAD, NEW, REPO, FakeApi, routes_for
from toolkit.features.deploy_merge import (
    CLOSE,
    MERGE,
    SKIP,
    judge,
    merge_enabled,
    pause_reason,
    required_contexts,
)
from toolkit.features.deploy_shape import load_declaration
from toolkit.features.product_registry import load_registry as load_products
from toolkit.features.review_attestation import DEFAULT_REGISTRY

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / DEFAULT_REGISTRY
REQUIRED = ("Validate", "Detect Changes", "review-attestation", "Tests", "deploy-shape")


class MergeApi(FakeApi):
    """FakeApi plus the PR fields only the merge step reads."""

    def __init__(self, routes: dict[str, Any], *, draft: bool = False, state: str = "clean", **kw: Any) -> None:
        super().__init__(routes, **kw)
        self.draft, self.state = draft, state

    def json(self, path: str) -> Any:
        value = super().json(path)
        if path == f"repos/{REPO}/pulls/7":
            value = {**value, "number": 7, "draft": self.draft, "mergeable_state": self.state}
        return value


def green(statuses: dict[str, str] | None = None, checks: dict[str, str] | None = None) -> dict[str, Any]:
    """Routes for the commit's statuses and check-runs; every required context green by default."""
    # review-attestation and deploy-shape are commit statuses (#2717); the rest are check-runs.
    statuses = {"review-attestation": "success", "deploy-shape": "success", **(statuses or {})}
    checks = {"Validate": "success", "Detect Changes": "success", "Tests": "success", **(checks or {})}
    return {
        f"repos/{REPO}/commits/{HEAD}/status": {
            "statuses": [{"context": c, "state": s} for c, s in statuses.items() if s is not None]
        },
        f"repos/{REPO}/commits/{HEAD}/check-runs?per_page=100": {
            "check_runs": [
                {"id": i, "name": n, "status": "completed", "conclusion": c}
                for i, (n, c) in enumerate(checks.items())
                if c is not None
            ]
        },
    }


def mergeable(**green_kw: Any) -> dict[str, Any]:
    return {**routes_for("web", "mlorentedev/web"), **green(**green_kw)}


@pytest.fixture(scope="module")
def decl():
    return load_declaration(REGISTRY_PATH)


@pytest.fixture(scope="module")
def products():
    return load_products(REPO_ROOT / "infra/config/products.yaml").products


def run(api: MergeApi, decl, products, paused: str | None = None):
    return judge(7, REPO, api, decl, products, REQUIRED, paused=paused)


class TestMerge:
    def test_a_mechanical_green_clean_pr_merges_at_the_judged_sha(self, decl, products) -> None:
        decision = run(MergeApi(mergeable()), decl, products)
        assert (decision.action, decision.head_sha) == (MERGE, HEAD), decision.reason

    @pytest.mark.parametrize("conclusion", ["neutral", "skipped"])
    def test_a_neutral_or_skipped_check_run_passes(self, decl, products, conclusion: str) -> None:
        decision = run(MergeApi(mergeable(checks={"Detect Changes": conclusion})), decl, products)
        assert decision.action == MERGE, decision.reason

    def test_an_unstable_pr_with_every_required_context_green_merges(self, decl, products) -> None:
        """`unstable` means a context branch protection does not require is not passing.

        #2883 sat 6.5h on `add-to-project` hitting a rate limit; the merge button
        accepts that state, and the required contexts are checked on their own."""
        decision = run(MergeApi(mergeable(), state="unstable"), decl, products)
        assert decision.action == MERGE, decision.reason


class TestUnstableExcusesOnlyTheAllowList:
    """#2983: `unstable` means some context that is not required is failing. The judge
    names which: only `add-to-project` (#2883, a rate limit) is excused. Drift is the
    generator-equals-values check (ADR-027), and a merge with it red is not mechanical."""

    def test_add_to_project_failing_still_merges(self, decl, products) -> None:
        routes = mergeable(checks={"add-to-project": "failure"})
        decision = run(MergeApi(routes, state="unstable"), decl, products)
        assert decision.action == MERGE, decision.reason

    @pytest.mark.parametrize("context", ["Drift / staging", "Drift / prod", "GitGuardian Security Checks"])
    def test_any_other_red_context_refuses(self, decl, products, context: str) -> None:
        routes = mergeable(checks={context: "failure"})
        decision = run(MergeApi(routes, state="unstable"), decl, products)
        assert decision.action == SKIP and context in decision.reason, decision.reason

    def test_a_red_status_that_is_not_required_refuses_too(self, decl, products) -> None:
        routes = mergeable(statuses={"pr-agent": "failure"})
        decision = run(MergeApi(routes, state="unstable"), decl, products)
        assert decision.action == SKIP and "pr-agent" in decision.reason, decision.reason

    def test_a_context_still_running_refuses(self, decl, products) -> None:
        """Fail closed: the workflow_run trigger judges again when it finishes."""
        routes = mergeable(checks={"Drift / staging": "success"})
        runs = routes[f"repos/{REPO}/commits/{HEAD}/check-runs?per_page=100"]["check_runs"]
        runs[-1] = {**runs[-1], "status": "in_progress", "conclusion": None}
        decision = run(MergeApi(routes), decl, products)
        assert decision.action == SKIP and "Drift / staging" in decision.reason, decision.reason


class TestEachConditionRefusesAlone:
    def test_not_mechanical(self, decl, products) -> None:
        routes = mergeable()
        routes[f"repos/{REPO}/pulls/7/files?per_page=100"] = [{"filename": "README.md", "status": "modified"}]
        assert run(MergeApi(routes), decl, products).action == SKIP

    # The receivers open deploy PRs with RELEASE_PLEASE_TOKEN, the operator's PAT, so
    # the author GitHub shows is the operator; the bot name is what the commits carry.
    @pytest.mark.parametrize("login", ["mlorentedev", "kubelab-bot"])
    def test_a_deploy_branch_and_author_grant_nothing(self, decl, products, login: str) -> None:
        """review-2 F2: the name and the author are what anyone can mint. A PR from
        `deploy/staging-web` by either identity with a non-mechanical diff is skipped."""
        routes = mergeable()
        routes[f"repos/{REPO}/pulls/7/files?per_page=100"] = [{"filename": "README.md", "status": "modified"}]

        class Named(MergeApi):
            def json(self, path: str) -> Any:
                value = super().json(path)
                if path == f"repos/{REPO}/pulls/7":
                    head = {**value["head"], "ref": "deploy/staging-web"}
                    value = {**value, "head": head, "user": {"login": login}}
                return value

        assert run(Named(routes), decl, products).action == SKIP

    def test_unknown(self, decl, products) -> None:
        routes = mergeable()
        routes["repos/mlorentedev/web/commits/0ddba11"] = RuntimeError("HTTP 502")
        assert run(MergeApi(routes), decl, products).action == SKIP

    @pytest.mark.parametrize("context", REQUIRED)
    def test_a_missing_required_context(self, decl, products, context: str) -> None:
        routes = mergeable(statuses={context: None}, checks={context: None})
        decision = run(MergeApi(routes), decl, products)
        assert decision.action == SKIP and context in decision.reason

    @pytest.mark.parametrize("state", ["failure", "error", "pending"])
    def test_a_status_that_is_not_success(self, decl, products, state: str) -> None:
        decision = run(MergeApi(mergeable(statuses={"review-attestation": state})), decl, products)
        assert decision.action == SKIP

    @pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
    def test_a_check_run_that_did_not_pass(self, decl, products, conclusion: str) -> None:
        assert run(MergeApi(mergeable(checks={"Tests": conclusion})), decl, products).action == SKIP

    def test_a_check_run_still_running(self, decl, products) -> None:
        routes = mergeable()
        runs = routes[f"repos/{REPO}/commits/{HEAD}/check-runs?per_page=100"]["check_runs"]
        runs[0] = {**runs[0], "status": "in_progress", "conclusion": None}
        assert run(MergeApi(routes), decl, products).action == SKIP

    def test_a_context_reported_twice_needs_both_green(self, decl, products) -> None:
        """A same-named status and check-run: the red one is not outvoted."""
        routes = mergeable(statuses={"Tests": "failure"})
        assert run(MergeApi(routes), decl, products).action == SKIP

    def test_unstable_does_not_excuse_a_red_required_context(self, decl, products) -> None:
        routes = mergeable(checks={"Tests": "failure"})
        decision = run(MergeApi(routes, state="unstable"), decl, products)
        assert decision.action == SKIP and "required contexts not passing" in decision.reason

    def test_the_latest_run_of_a_check_is_the_one_that_counts(self, decl, products) -> None:
        routes = mergeable()
        runs = routes[f"repos/{REPO}/commits/{HEAD}/check-runs?per_page=100"]["check_runs"]
        runs.append({"id": 99, "name": "Tests", "status": "completed", "conclusion": "failure"})
        assert run(MergeApi(routes), decl, products).action == SKIP

    @pytest.mark.parametrize("state", ["blocked", "behind", "dirty", "unknown", "draft", "has_hooks", None])
    def test_a_merge_state_that_is_not_clean_or_unstable(self, decl, products, state: str | None) -> None:
        assert run(MergeApi(mergeable(), state=state), decl, products).action == SKIP

    def test_a_head_that_moves_after_the_verdict(self, decl, products) -> None:
        """evaluate() reads the head twice; the judge's final read is a third."""
        api = MergeApi(mergeable(), heads=[HEAD, HEAD, HEAD, "d" * 40])
        assert run(api, decl, products).action == SKIP

    def test_a_verdict_about_another_sha_is_refused_before_contexts_are_read(self, decl, products) -> None:
        """The judge read head d; evaluate() then judged HEAD. That verdict says nothing about d.

        Defence in depth: the final re-read would also catch it, later and under another reason.
        Contexts are routed for HEAD only, so reading them at d first would raise and answer
        "cannot judge": the prefix asserts the order, not only the outcome."""
        api = MergeApi(mergeable(), heads=["d" * 40, HEAD, HEAD])
        decision = run(api, decl, products)
        assert decision.action == SKIP and decision.reason.startswith("mechanical:"), decision.reason

    def test_a_draft_is_never_touched(self, decl, products) -> None:
        assert run(MergeApi(mergeable(), draft=True), decl, products).action == SKIP


class TestEmpty:
    def test_an_empty_pr_is_closed(self, decl, products) -> None:
        """#2649: after "Update branch" master already carried the tag, and it merged empty."""
        decision = run(MergeApi({f"repos/{REPO}/pulls/7/files?per_page=100": []}), decl, products)
        assert (decision.action, decision.head_sha) == (CLOSE, HEAD)

    def test_an_empty_draft_is_left_alone(self, decl, products) -> None:
        api = MergeApi({f"repos/{REPO}/pulls/7/files?per_page=100": []}, draft=True)
        assert run(api, decl, products).action == SKIP

    def test_an_unreadable_file_list_is_not_empty(self, decl, products) -> None:
        api = MergeApi({f"repos/{REPO}/pulls/7/files?per_page=100": RuntimeError("HTTP 502")})
        assert run(api, decl, products).action == SKIP


class TestSwitch:
    """Absent, false, or anything but the boolean true is off. Never an error:
    `load_declaration` must keep publishing deploy-shape whatever this key holds."""

    @pytest.mark.parametrize("value", [None, False, "true", 1, "yes"])
    def test_anything_but_true_is_off(self, tmp_path, value) -> None:
        block = {} if value is None else {"merge": value}
        path = tmp_path / "r.json"
        path.write_text(json.dumps({"mechanical": block}), encoding="utf-8")
        assert merge_enabled(path) is False

    def test_true_is_on(self, tmp_path) -> None:
        path = tmp_path / "r.json"
        path.write_text(json.dumps({"mechanical": {"merge": True}}), encoding="utf-8")
        assert merge_enabled(path) is True

    def test_an_unreadable_registry_is_off(self, tmp_path) -> None:
        path = tmp_path / "r.json"
        path.write_text("{not json", encoding="utf-8")
        assert merge_enabled(path) is False

    def test_the_committed_switch_is_on(self) -> None:
        """PR 4 flipped it, together with tests/test_deploy_shape_widening.py."""
        assert merge_enabled(REGISTRY_PATH) is True


class TestRequiredContexts:
    def test_read_from_the_branch_protection_declaration(self) -> None:
        contexts = required_contexts(REPO_ROOT / "infra/config/values/common.yaml", REPO, "master")
        assert "deploy-shape" in contexts and "review-attestation" in contexts

    def test_an_undeclared_branch_is_an_error(self) -> None:
        with pytest.raises(KeyError):
            required_contexts(REPO_ROOT / "infra/config/values/common.yaml", REPO, "no-such-branch")


class TestWorkflowTriggers:
    def test_the_default_branch_guard_binds_only_dispatch(self) -> None:
        """The guard binds only dispatch, the one event that can name another branch."""
        import yaml

        wf = yaml.safe_load((REPO_ROOT / ".github/workflows/deploy-merge.yml").read_text(encoding="utf-8"))
        # Exact: an absent guard would let a dispatch on a branch judge with that branch's code.
        assert wf["jobs"]["merge"].get("if") == (
            "github.event_name != 'workflow_dispatch' || github.ref_name == github.event.repository.default_branch"
        )


RUNS = f"repos/{REPO}/actions/workflows/deploy-verify.yml/runs?branch=master&status=completed&per_page=50"


def verify_runs(*runs: tuple[int, str, list[str]]) -> dict[str, Any]:
    """Routes for deploy-verify's runs, newest first: (id, run conclusion, job conclusions)."""
    routes: dict[str, Any] = {
        RUNS: {
            "workflow_runs": [
                {"id": i, "conclusion": c, "html_url": f"https://example.invalid/runs/{i}"} for i, c, _ in runs
            ]
        }
    }
    for i, _, jobs in runs:
        routes[f"repos/{REPO}/actions/runs/{i}/jobs?per_page=100"] = {
            "jobs": [{"name": f"job{n}", "conclusion": j} for n, j in enumerate(jobs)]
        }
    return routes


class TestDeployVerifyPause:
    """#3062 F11 option A: while deploy-verify is red on master, nothing merges
    unattended. Its noise runs (a skipped job, concluded `success`) are not a verdict."""

    def test_the_latest_real_run_green_does_not_pause(self) -> None:
        api = FakeApi(verify_runs((3, "success", ["skipped"]), (2, "success", ["success", "skipped"])))
        assert pause_reason(api, REPO, "master") is None

    def test_a_red_run_under_noise_pauses_and_names_it(self) -> None:
        api = FakeApi(verify_runs((3, "success", ["skipped"]), (2, "failure", ["failure", "skipped"])))
        reason = pause_reason(api, REPO, "master")
        assert reason is not None and "https://example.invalid/runs/2" in reason

    def test_a_green_run_after_a_red_one_clears_it(self) -> None:
        api = FakeApi(verify_runs((3, "success", ["success"]), (2, "failure", ["failure"])))
        assert pause_reason(api, REPO, "master") is None

    def test_only_noise_in_the_page_fails_closed(self) -> None:
        api = FakeApi(verify_runs((3, "success", ["skipped"]), (2, "success", ["skipped"])))
        assert pause_reason(api, REPO, "master") is not None

    def test_a_green_run_with_no_jobs_is_not_a_verdict(self) -> None:
        api = FakeApi(verify_runs((3, "success", []), (2, "failure", ["failure"])))
        assert pause_reason(api, REPO, "master") is not None

    def test_a_run_that_failed_to_start_pauses(self) -> None:
        api = FakeApi(verify_runs((3, "startup_failure", []), (2, "success", ["success"])))
        assert pause_reason(api, REPO, "master") is not None

    def test_no_runs_fails_closed(self) -> None:
        assert pause_reason(FakeApi({RUNS: {"workflow_runs": []}}), REPO, "master") is not None

    def test_unreadable_runs_fail_closed(self) -> None:
        assert pause_reason(FakeApi({RUNS: RuntimeError("403")}), REPO, "master") is not None

    def test_unreadable_jobs_fail_closed(self) -> None:
        routes = verify_runs((3, "success", ["success"]))
        routes[f"repos/{REPO}/actions/runs/3/jobs?per_page=100"] = RuntimeError("403")
        assert pause_reason(FakeApi(routes), REPO, "master") is not None

    def test_a_pause_skips_a_mergeable_pr(self, decl, products) -> None:
        assert run(MergeApi(mergeable()), decl, products).action == MERGE, "the fixture must merge unpaused"
        decision = run(MergeApi(mergeable()), decl, products, paused="deploy-verify is red")
        assert decision.action == SKIP and "deploy-verify is red" in decision.reason, decision.reason

    def test_a_pause_skips_even_an_empty_pr(self, decl, products) -> None:
        """The decision on #3062 is "skips every PR"; an empty one is closed a run later."""
        routes = mergeable()
        routes[f"repos/{REPO}/pulls/7/files?per_page=100"] = []
        assert run(MergeApi(routes), decl, products, paused="red").action == SKIP


class TestSquashMessage:
    """#3062 F6: the squash message comes from what was judged, never from the PR's
    title or body, which the judge does not read (`[skip ci]`, `feat!:`)."""

    def test_a_merge_carries_a_subject_and_body_from_the_judged_app_and_tag(self, decl, products) -> None:
        decision = run(MergeApi(mergeable()), decl, products)
        assert decision.action == MERGE, decision.reason
        assert decision.subject == f"chore(staging): deploy web {NEW} (#7)"
        assert decision.body == f"Staging promotion of web to {NEW}, merged as a mechanical deploy (#1619)."

    def test_a_skip_carries_no_message(self, decl, products) -> None:
        decision = run(MergeApi(mergeable()), decl, products, paused="red")
        assert decision.subject is None and decision.body is None


def test_the_cli_writes_the_pause_into_the_decisions(tmp_path, monkeypatch) -> None:
    """The workflow's `Report a pause` step reads it: a pause makes every decision a
    skip, so without it a paused run explains nothing (#3086 review)."""
    from typer.testing import CliRunner

    from toolkit.cli.tools import app
    from toolkit.features import deploy_shape

    routes = {
        f"repos/{REPO}": {"default_branch": "master"},
        f"repos/{REPO}/pulls?state=open&base=master&per_page=100&page=1": [],
        **verify_runs((2, "failure", ["failure"])),
    }
    monkeypatch.setattr(deploy_shape, "GhApi", lambda: FakeApi(routes))
    out = tmp_path / "decisions.json"
    result = CliRunner().invoke(app, ["deploy-merge", "--repo", REPO, "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "https://example.invalid/runs/2" in json.loads(out.read_text())["paused"]
