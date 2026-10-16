"""Unit tests for the Vikunja platform reconciler (idempotent labels and webhooks)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from toolkit.features.vikunja_client import VikunjaClient
from toolkit.features.vikunja_reconciler import VikunjaReconciler


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=VikunjaClient)
    return client


def test_reconciler_creates_missing_labels_and_webhooks(mock_client: MagicMock) -> None:
    # Initial state: no labels, and one project needing a webhook
    mock_client.get_labels.return_value = []
    mock_client.get_projects.return_value = [{"id": 10, "title": "kubelab-core"}]
    mock_client.get_webhooks.return_value = []

    reconciler = VikunjaReconciler(client=mock_client)
    res = reconciler.reconcile()

    assert res.labels_created >= 6
    assert res.webhooks_created == 1
    assert res.changed is True

    mock_client.create_label.assert_any_call(title="agent:delegable", hex_color="#4a90e2")
    mock_client.create_label.assert_any_call(title="type:spec", hex_color="#2ecc71")
    mock_client.create_webhook.assert_called_once_with(
        project_id=10,
        target_url="http://n8n:5678/webhook/agent-dispatcher",
        events=["task.updated", "task.created"],
    )


def test_reconciler_is_strictly_idempotent_when_resources_exist(mock_client: MagicMock) -> None:
    # State: all labels and webhooks already exist
    mock_client.get_labels.return_value = [
        {"id": 1, "title": "type:spec"},
        {"id": 2, "title": "type:bug"},
        {"id": 3, "title": "type:chore"},
        {"id": 4, "title": "agent:delegable"},
        {"id": 5, "title": "priority:P0"},
        {"id": 6, "title": "priority:P1"},
        {"id": 7, "title": "priority:P2"},
        {"id": 8, "title": "priority:P3"},
    ]
    mock_client.get_projects.return_value = [{"id": 10, "title": "kubelab-core"}]
    mock_client.get_webhooks.return_value = [{"id": 100, "target_url": "http://n8n:5678/webhook/agent-dispatcher"}]

    reconciler = VikunjaReconciler(client=mock_client)
    res = reconciler.reconcile()

    assert res.labels_created == 0
    assert res.webhooks_created == 0
    assert res.changed is False

    mock_client.create_label.assert_not_called()
    mock_client.create_webhook.assert_not_called()


def test_the_client_has_no_namespace_endpoint_because_vikunja_1_0_removed_it() -> None:
    """`GET /namespaces` answers 404 on vikunja/vikunja:1.0.0 (#1701).

    The old tests passed against a fake that answered whatever the client asked,
    so they certified an endpoint the server no longer has. A client that cannot
    make the call cannot be certified by a fake for it.
    """
    assert not hasattr(VikunjaClient, "get_namespaces")
    assert not hasattr(VikunjaClient, "create_namespace")


def test_a_rejected_call_exits_with_the_servers_answer_not_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token that authenticates but lacks a scope (401 on `GET /labels`) is the likeliest failure."""
    from typer.testing import CliRunner

    from toolkit.cli.sync import app
    from toolkit.features import vikunja_client
    from toolkit.features.vikunja_client import VikunjaError

    def refuse(self: object) -> list[dict[str, object]]:
        raise VikunjaError("Vikunja API error 401: token lacks labels")

    monkeypatch.setattr(vikunja_client.VikunjaClient, "get_labels", refuse)
    result = CliRunner().invoke(app, ["vikunja", "--env", "staging", "--url", "http://x/api/v1", "--token", "t"])
    assert result.exit_code == 1
    assert "401" in result.output and "Traceback" not in result.output
