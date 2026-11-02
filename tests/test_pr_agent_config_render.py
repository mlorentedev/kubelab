"""TOOL-080 PR 4, AC4: the rendered prod ConfigMap carries the review-only contract.

Rendered, not read from the source `.env` file, for the reason
`test_vikunja_registration_render.py` and `test_n8n_code_node_runtime_render.py`
give at length: a Kustomize overlay that stops applying is invisible to a check
that only reads files on disk.

The three settings this pins are load-bearing, per the proposal:

- `GITEA__PR_COMMANDS` / `GITEA__PUSH_COMMANDS` exactly `["/review"]` — upstream's
  default also runs `/describe` (rewrites the PR title/body) and `/improve`.
- No `GITEA__REPO_SETTING` key at all — that key is what makes the provider read
  a repository `.pr_agent.toml`, and at v0.45.0 it reads it at the PR's HEAD SHA,
  letting the PR author rewrite the reviewer's own configuration in the change
  under review.
- `PR_REVIEWER__FINAL_UPDATE_MESSAGE=false` with `PERSISTENT_COMMENT=true` — the
  2026-09-24 lab measured upstream's default posting a second "updated" comment
  on every push, next to the edited one (verification.md, "Delivery").
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIGMAP_PREFIX = "pr-agent-config"
REVIEWER_POOL = REPO_ROOT / "harness" / "reviewer-pool.json"
#: The completion cap NaN applies to a request that sends no `max_tokens`.
NAN_DEFAULT_COMPLETION_CAP = 32768

#: Every key this ConfigMap must carry, and its exact rendered string value.
#: Values are always strings coming out of a kustomize `envs:` file — including
#: the two list-shaped ones, which PR-Agent (LiteLLM/pydantic-settings) parses
#: from the JSON-looking string itself, the same as `.github/workflows/
#: pr-agent.yml`'s `CONFIG__FALLBACK_MODELS: '["openai/deepseek-v4-flash"]'`.
REQUIRED_VALUES = {
    "CONFIG__GIT_PROVIDER": "gitea",
    "GITEA__URL": "https://gitea.kubelab.live",
    "OPENAI__API_BASE": "https://api.nan.builders/v1",
    "CONFIG__MODEL": "openai/glm5.3-flash",
    "CONFIG__RETRY_SAME_MODEL_ON_TIMEOUT": "false",
    "CONFIG__NUM_RETRIES": "0",
    "CONFIG__AI_TIMEOUT": "360",
    "LITELLM__CUSTOM_LLM_PROVIDER": "openai",
    "LITELLM__FORCE_STREAMING_CUSTOM_LLM_PROVIDER": "openai",
    "LITELLM__FORCE_STREAMING_API_BASE_SUBSTRINGS": '["api.nan.builders"]',
    "PR_REVIEWER__NUM_MAX_FINDINGS": "5",
    "CONFIG__FALLBACK_MODELS": '["openai/deepseek-v4-flash", "openai/mimo-v2.6-flash"]',
    "CONFIG__CUSTOM_MODEL_MAX_TOKENS": "200000",
    "CONFIG__MAX_MODEL_TOKENS": "200000",
    "CONFIG__MAX_OUTPUT_TOKENS": "65536",
    "CONFIG__PUBLISH_OUTPUT_PROGRESS": "false",
    "GITEA__PR_COMMANDS": '["/review"]',
    "GITEA__PUSH_COMMANDS": '["/review"]',
    "GITEA__HANDLE_PUSH_TRIGGER": "true",
    "PR_REVIEWER__PERSISTENT_COMMENT": "true",
    "PR_REVIEWER__FINAL_UPDATE_MESSAGE": "false",
    "PR_REVIEWER__ENABLE_REVIEW_LABELS_EFFORT": "false",
    "PR_REVIEWER__ENABLE_REVIEW_LABELS_SECURITY": "false",
    "CONFIG__REPO_CONTEXT_FROM_DEFAULT_BRANCH": "true",
}


def _kustomize(path: str) -> list[dict]:
    """Render a Kustomize directory, or skip loudly if kubectl is unavailable."""
    if shutil.which("kubectl") is None:
        pytest.skip(
            "CANNOT CHECK: kubectl is not installed, so the rendered output cannot be "
            "produced. This is not a pass -- TOOL-080 AC4 is unverified here."
        )
    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"kubectl kustomize {path} failed:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _pr_agent_config() -> dict:
    docs = _kustomize("infra/k8s/overlays/prod")
    matches = [
        doc
        for doc in docs
        if doc.get("kind") == "ConfigMap" and str(doc.get("metadata", {}).get("name", "")).startswith(CONFIGMAP_PREFIX)
    ]
    assert len(matches) == 1, (
        f"expected exactly one ConfigMap named {CONFIGMAP_PREFIX}-* in the prod render, "
        f"found {len(matches)}: {[m['metadata']['name'] for m in matches]}."
    )
    return matches[0]


class TestReviewOnlyContract:
    def test_every_required_key_has_its_exact_value(self) -> None:
        data = _pr_agent_config().get("data") or {}
        missing = sorted(set(REQUIRED_VALUES) - set(data))
        assert not missing, f"the prod pr-agent-config render is missing {missing}"

        mismatched = {k: data[k] for k, expected in REQUIRED_VALUES.items() if data.get(k) != expected}
        assert not mismatched, f"rendered values disagree with the contract: {mismatched}"

    def test_the_prompt_cap_is_stated_and_matches_the_model_budget(self) -> None:
        """PR-Agent caps every prompt at `config.max_model_tokens`, whose upstream
        default is 32000 (configuration.toml at v0.45.0), whatever
        `custom_model_max_tokens` says (`get_max_tokens`). Left unset, the forge
        reviews a third-sized diff and reports the rest as skipped "because of the
        token budget". The GitHub workflow states both caps; so must the forge.
        """
        data = _pr_agent_config().get("data") or {}
        assert "CONFIG__MAX_MODEL_TOKENS" in data, "the prompt cap falls back to PR-Agent's 32000 default"
        assert data["CONFIG__MAX_MODEL_TOKENS"] == data.get("CONFIG__CUSTOM_MODEL_MAX_TOKENS"), (
            "the prompt cap and the model budget disagree, so the smaller one silently wins"
        )

    def test_the_output_cap_is_above_the_providers_default(self) -> None:
        """Left unset, PR-Agent sends no `max_tokens` and NaN cuts every completion at
        32768 tokens, reasoning included. A flash model whose reasoning runs past that
        ends with `finish_reason: length` and no content, and the review is lost
        (TOOL-093, #1957). Measured 2026-10-18: deepseek-v4-flash stopped at exactly
        32768 with no `max_tokens` and finished at 41445 with 100000. A cap at or below
        the default would pass a presence check and change nothing on the wire.
        """
        data = _pr_agent_config().get("data") or {}
        cap = int(data.get("CONFIG__MAX_OUTPUT_TOKENS", "0"))
        assert cap > NAN_DEFAULT_COMPLETION_CAP, (
            f"CONFIG__MAX_OUTPUT_TOKENS={cap} does not raise NaN's {NAN_DEFAULT_COMPLETION_CAP}-token default; "
            "PR-Agent treats 0 as unset, so this would restore the length failure"
        )

    def test_no_repo_setting_key_is_present(self) -> None:
        """Absence is the requirement: a repository .pr_agent.toml read at the PR

        head would let the PR author rewrite the reviewer's own configuration in
        the change under review (proposal, component 2).
        """
        data = _pr_agent_config().get("data") or {}
        assert "GITEA__REPO_SETTING" not in data

    def test_the_configmap_name_carries_a_content_hash(self) -> None:
        """A bare name would never roll the pod on a config edit (lesson-404)."""
        name = _pr_agent_config()["metadata"]["name"]
        assert name != CONFIGMAP_PREFIX, f"{name!r} carries no content hash"


def _nan_chain_from_pool() -> list[str]:
    """The forge chain the reviewer pool implies: its NaN members that carry a
    `pr_agent.weight`, in `pr_agent.forge_rank` order.

    `forge_rank` exists only in kubelab's copy of the pool (it is declared in the
    file's `$comment` as a divergence from dotfiles'). The CI draw is by `weight`
    and never reads it; the forge server cannot draw, so it tries members in turn
    and needs an order, which the weights are not: they are a spending share.

    NaN only, because this server sends every model through one api_base and
    one custom_llm_provider (lesson-596): an Anthropic member here would reach
    NaN as an OpenAI model. A `route: risk` member has no weight and is drawn
    only by CI's risk route, so it is not a fallback either.
    """
    pool = json.loads(REVIEWER_POOL.read_text(encoding="utf-8"))["pool"]
    members = [
        entry["pr_agent"]
        for entry in pool
        if entry.get("provider") == "nan" and "weight" in (entry.get("pr_agent") or {})
    ]
    members.sort(key=lambda pr_agent: pr_agent["forge_rank"])
    return [pr_agent["model"] for pr_agent in members]


class TestModelChainFollowsTheReviewerPool:
    """TOOL-117 (#2295) item 2: the forge reviewer reads the pool CI reads.

    The server takes its models once at start, so it cannot draw per review as
    CI does; the closest it gets is trying every NaN member in turn. Before this
    the chain was hand-written and fell behind the pool: the env named one
    fallback while the pool and CI had two.
    """

    def test_the_chain_is_the_pools_nan_members_in_forge_rank_order(self) -> None:
        data = _pr_agent_config().get("data") or {}
        chain = [data["CONFIG__MODEL"], *json.loads(data["CONFIG__FALLBACK_MODELS"])]
        expected = _nan_chain_from_pool()
        assert chain == expected, (
            f"the forge reviewer chain {chain} is not the reviewer pool's NaN members "
            f"by forge_rank {expected}. Edit infra/k8s/overlays/prod/pr-agent-config/"
            "pr-agent.env to match harness/reviewer-pool.json."
        )

    def test_the_model_that_finishes_reviews_first(self) -> None:
        """Owner decision 2026-10-18 (#1957): the chain is ordered by `forge_rank`, not by CI's
        spending weight, because the weight put mimo first, and mimo is the model a review
        most often loses to the ~600 s clock (lesson-601). Owner decision 2026-11-01: glm
        before deepseek. deepseek ran out of its 65536-token output cap mid-reasoning on 3
        of 7 forge reviews in 72 h (`finish_reason: length`, empty content), each costing
        about 9 minutes of two failed attempts before glm, which finished all three
        (lesson-685). The measurement lives in the lesson; this test only holds the order
        it led to, so a re-port of the pool cannot quietly bring an older order back."""
        data = _pr_agent_config().get("data") or {}

        assert data["CONFIG__MODEL"] == "openai/glm5.3-flash"
        assert json.loads(data["CONFIG__FALLBACK_MODELS"])[-1] == "openai/mimo-v2.6-flash"

    def test_the_pool_still_has_a_nan_member_to_review_with(self) -> None:
        """An empty derivation would make the test above compare nothing."""
        assert _nan_chain_from_pool(), "the reviewer pool has no weighted NaN member"
