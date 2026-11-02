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

from tests.test_deploy_shape import HEAD, REPO, FakeApi, routes_for
from toolkit.features.deploy_merge import CLOSE, MERGE, SKIP, judge, merge_enabled, required_contexts
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


def run(api: MergeApi, decl, products):
    return judge(7, REPO, api, decl, products, REQUIRED)


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


class TestEachConditionRefusesAlone:
    def test_not_mechanical(self, decl, products) -> None:
        routes = mergeable()
        routes[f"repos/{REPO}/pulls/7/files?per_page=100"] = [{"filename": "README.md", "status": "modified"}]
        assert run(MergeApi(routes), decl, products).action == SKIP

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

    def test_the_committed_switch_is_off(self) -> None:
        """PR 4 flips it, with the test in tests/test_deploy_shape_widening.py."""
        assert merge_enabled(REGISTRY_PATH) is False


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
