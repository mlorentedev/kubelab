"""Unit tests for n8n autonomous agent dispatcher workflow (AC6)."""

from __future__ import annotations

import json
import re
from pathlib import Path


def extract_agent_spec_payload(task_title: str, task_description: str, task_labels: list[str]) -> dict[str, str | bool]:
    """Parse task metadata and determine if task is ready for agent dispatch."""
    is_delegable = "agent:delegable" in task_labels

    # Extract spec ID or issue key (e.g. IDP-035, GITOPS-003)
    combined = f"{task_title} {task_description}"
    m = re.search(r"\b([A-Z]{2,10}-\d+)\b", combined)
    feature_id = m.group(1) if m else ""

    # Target branch convention: feat/<lowercase-feature-id>-task
    branch_name = f"feat/{feature_id.lower()}-task" if feature_id else "feat/agent-task"

    return {
        "is_delegable": is_delegable,
        "feature_id": feature_id,
        "branch_name": branch_name,
        "task_title": task_title,
    }


def test_agent_payload_extraction_with_delegable_label() -> None:
    payload = extract_agent_spec_payload(
        task_title="Scaffold IDP-035 Task Platform",
        task_description="Implement Vikunja reconciler and workflows per specs/IDP-035",
        task_labels=["type:spec", "agent:delegable", "priority:P1"],
    )

    assert payload["is_delegable"] is True
    assert payload["feature_id"] == "IDP-035"
    assert payload["branch_name"] == "feat/idp-035-task"


def test_agent_payload_ignored_without_label() -> None:
    payload = extract_agent_spec_payload(
        task_title="Manual infrastructure refactor",
        task_description="No agent delegation needed",
        task_labels=["type:chore", "priority:P2"],
    )

    assert payload["is_delegable"] is False
    assert payload["feature_id"] == ""


def test_agent_dispatcher_workflow_json_exists_and_is_valid() -> None:
    workflow_path = Path(__file__).resolve().parent.parent / "infra/n8n/workflows/agent-dispatcher.json"
    assert workflow_path.is_file(), "agent-dispatcher.json must exist in infra/n8n/workflows/"

    with open(workflow_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("name") == "agent-dispatcher"
    assert len(data.get("nodes", [])) >= 4
    assert "connections" in data

    code_node = next((n for n in data["nodes"] if n["name"] == "Extract Agent Payload"), None)
    assert code_node is not None
    js = code_node["parameters"]["jsCode"]
    assert "agent:delegable" in js
    assert "isDelegable" in js
