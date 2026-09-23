"""Tests for n8n import feature (TOOL-009, IDP-035)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from toolkit.features.configuration import ConfigurationManager
from toolkit.features.n8n_import import (
    N8N_IMPORT_CATALOG,
    PlaceholderError,
    import_n8n_workflow,
    read_workflow_ids,
    render_credential,
    resolve_placeholders,
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


class TestPlaceholderResolution:
    """`RESOLVE_*` tokens are filled from SSOT at import time, or the import refuses.

    Both refusals are asserted because neither had ever been observed failing —
    found by mutation: replacing `if not value:` with `if False:` left all 30
    tests green, which makes the guard a claim in executable syntax rather than a
    check (lesson-306).
    """

    def _cm(self, config: dict[str, object]) -> MagicMock:
        cm = MagicMock()
        cm.get_merged_config.return_value = config
        return cm

    def test_a_declared_token_is_substituted(self) -> None:
        cm = self._cm({"apps": {"services": {"core": {"vikunja": {"default_project": "Bitacora"}}}}})
        assert resolve_placeholders("x = 'RESOLVE_VIKUNJA_DEFAULT_PROJECT';", cm) == "x = 'Bitacora';"

    def test_text_without_placeholders_is_untouched(self) -> None:
        """The early return matters: it keeps the resolver from decrypting or
        reading config for the three workflows that carry no token."""
        cm = MagicMock()
        assert resolve_placeholders("nothing to see", cm) == "nothing to see"
        cm.get_merged_config.assert_not_called()

    def test_an_unmapped_token_refuses(self) -> None:
        """An unsubstituted token reaches the running workflow as a literal
        string — it fails closed, but in production and naming no cause."""
        with pytest.raises(PlaceholderError, match="RESOLVE_NOT_MAPPED"):
            resolve_placeholders("y = 'RESOLVE_NOT_MAPPED';", self._cm({}))

    @pytest.mark.parametrize(
        "config",
        [
            pytest.param({}, id="path-absent"),
            pytest.param({"apps": {"services": {"core": {"vikunja": {"default_project": ""}}}}}, id="empty-string"),
            pytest.param({"apps": {"services": {"core": {"vikunja": {"default_project": "   "}}}}}, id="whitespace"),
            pytest.param({"apps": {"services": {"core": {"vikunja": {}}}}}, id="key-absent"),
        ],
    )
    def test_a_declared_path_holding_nothing_refuses(self, config: dict[str, object]) -> None:
        """Substituting an empty value is worse than not substituting: the
        workflow then searches for a project titled `''`, matches nothing, and
        answers a correct-looking 422 that names no cause."""
        with pytest.raises(PlaceholderError, match="absent or empty"):
            resolve_placeholders("z = 'RESOLVE_VIKUNJA_DEFAULT_PROJECT';", self._cm(config))


def test_import_n8n_workflow_dry_run() -> None:
    """The secret is mocked; the CONFIG is real, and that asymmetry is the point.

    A committed workflow may carry `RESOLVE_*` placeholders the import fills from
    `common.yaml`. Mocking `get_merged_config` too would let this pass against a
    declaration that does not exist — the mock would answer for a key nobody had
    written, which is the failure lesson-440 records. Reading the real config
    means this test also pins that every placeholder in every catalog workflow
    resolves against the SSOT actually shipped.
    """
    mock_cm = MagicMock()
    mock_cm.get_secret_by_path.return_value = "dummy-secret-token"
    mock_cm.get_merged_config.return_value = ConfigurationManager(env="staging").get_merged_config()
    with patch("toolkit.features.n8n_import.ConfigurationManager", return_value=mock_cm):
        result = import_n8n_workflow("staging", REPO_ROOT, dry_run=True)
        assert result is True
