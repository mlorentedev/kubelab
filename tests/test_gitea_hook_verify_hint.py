"""#1849: the advice printed after a hook is written belongs to that hook.

Since TOOL-080 a reconcile can write the PR-Agent hook alone, and it printed n8n's
advice (check a Vikunja task) for it, which proves nothing about PR-Agent. Each
declaration now carries its own `verify_hint`, and the hints printed are those of
the hooks actually written, each once.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.features.gitea_repos import (
    HookDeclaration,
    WebhookSpec,
    load_webhooks,
    verify_hints,
)

COMMON = Path(__file__).resolve().parents[1] / "infra/config/values/common.yaml"


def _hook(url: str, hint: str) -> HookDeclaration:
    spec = WebhookSpec(url=url, content_type="json", events=("push",), active=True, branch_filter="*", type="gitea")
    return HookDeclaration(spec=spec, secret_key="k", verify_hint=hint)


N8N = _hook("https://n8n.example/hook", "check the Vikunja task")
AGENT = _hook("https://agent.example/hook", "check for a review comment")
SILENT = _hook("https://silent.example/hook", "")


def test_only_the_written_hook_s_hint_is_printed() -> None:
    assert verify_hints([("o/r", AGENT.spec.url)], (N8N, AGENT)) == ["check for a review comment"]


def test_a_hint_is_printed_once_however_many_repositories_got_the_hook() -> None:
    written = [("o/a", N8N.spec.url), ("o/b", N8N.spec.url), ("o/a", AGENT.spec.url)]
    assert verify_hints(written, (N8N, AGENT)) == ["check the Vikunja task", "check for a review comment"]


def test_nothing_written_prints_nothing_and_an_empty_hint_is_skipped() -> None:
    assert verify_hints([], (N8N, AGENT)) == []
    assert verify_hints([("o/r", SILENT.spec.url)], (SILENT,)) == []


@pytest.fixture(scope="module")
def declared() -> dict[str, HookDeclaration]:
    return {h.spec.url: h for h in load_webhooks(yaml.safe_load(COMMON.read_text(encoding="utf-8")))}


def test_every_declared_hook_says_how_to_verify_it(declared: dict[str, HookDeclaration]) -> None:
    assert declared and all(h.verify_hint.strip() for h in declared.values())


def test_the_pr_agent_hook_does_not_send_the_operator_to_vikunja(declared: dict[str, HookDeclaration]) -> None:
    agent = next(h for url, h in declared.items() if "pr-agent" in url)
    n8n = next(h for url, h in declared.items() if "n8n" in url)
    assert "Vikunja" in n8n.verify_hint
    assert "Vikunja" not in agent.verify_hint
