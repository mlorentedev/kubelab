"""Tests for n8n import feature (TOOL-009, IDP-035)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolkit.features.n8n_import import (
    N8N_IMPORT_CATALOG,
    import_n8n_workflow,
    read_workflow_ids,
    render_credential,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_n8n_import_catalog_contains_expected_workflows() -> None:
    expected = {
        "notify-router.json",
        "multi-forge-sync.json",
        "slack-task-capture.json",
        "agent-dispatcher.json",
    }
    catalog_names = {s.workflow_path.name for s in N8N_IMPORT_CATALOG}
    assert expected.issubset(catalog_names), f"Missing workflows in catalog: {expected - catalog_names}"


def test_read_workflow_ids_on_all_catalog_workflows() -> None:
    for spec in N8N_IMPORT_CATALOG:
        full_path = REPO_ROOT / spec.workflow_path
        assert full_path.is_file(), f"Workflow file must exist: {full_path}"
        with open(full_path, encoding="utf-8") as f:
            data = json.load(f)

        workflow_id, credential_id = read_workflow_ids(data)
        assert workflow_id, f"Workflow {spec.workflow_path.name} must have a valid root id"
        if spec.workflow_path.name in {"notify-router.json", "agent-dispatcher.json"}:
            assert credential_id is not None, f"Workflow {spec.workflow_path.name} must have a credential id"
        else:
            # multi-forge and slack handle authentication via code node (HMAC)
            assert credential_id is None


def test_render_credential_shape() -> None:
    cred_json = render_credential("cred-123", "my-cred", "secret-token")
    data = json.loads(cred_json)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == "cred-123"
    assert data[0]["name"] == "my-cred"
    assert data[0]["type"] == "httpHeaderAuth"
    assert data[0]["data"]["value"] == "Bearer secret-token"


def test_import_n8n_workflow_dry_run() -> None:
    result = import_n8n_workflow("staging", REPO_ROOT, dry_run=True)
    assert result is True
