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

import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIGMAP_PREFIX = "pr-agent-config"

#: Every key this ConfigMap must carry, and its exact rendered string value.
#: Values are always strings coming out of a kustomize `envs:` file — including
#: the two list-shaped ones, which PR-Agent (LiteLLM/pydantic-settings) parses
#: from the JSON-looking string itself, the same as `.github/workflows/
#: pr-agent.yml`'s `CONFIG__FALLBACK_MODELS: '["openai/deepseek-v4-flash"]'`.
REQUIRED_VALUES = {
    "CONFIG__GIT_PROVIDER": "gitea",
    "GITEA__URL": "https://gitea.kubelab.live",
    "OPENAI__API_BASE": "https://api.nan.builders/v1",
    "CONFIG__MODEL": "openai/mimo-v2.6-flash",
    "CONFIG__RETRY_SAME_MODEL_ON_TIMEOUT": "false",
    "CONFIG__NUM_RETRIES": "0",
    "CONFIG__AI_TIMEOUT": "360",
    "PR_REVIEWER__NUM_MAX_FINDINGS": "5",
    "CONFIG__FALLBACK_MODELS": '["openai/deepseek-v4-flash"]',
    "CONFIG__CUSTOM_MODEL_MAX_TOKENS": "200000",
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
