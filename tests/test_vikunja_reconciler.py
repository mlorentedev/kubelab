"""Unit tests for Vikunja platform reconciler (idempotent namespaces, labels, webhooks)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from toolkit.features.vikunja_client import VikunjaClient
from toolkit.features.vikunja_reconciler import VikunjaReconciler


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=VikunjaClient)
    return client


def test_reconciler_creates_missing_namespaces_and_labels(mock_client: MagicMock) -> None:
    # Initial state: empty namespaces and labels
    mock_client.get_namespaces.return_value = []
    mock_client.get_labels.return_value = []

    reconciler = VikunjaReconciler(client=mock_client)
    res = reconciler.reconcile()

    # Verify created namespaces (kubelab, personal, teledyne)
    assert res.namespaces_created == 3
    assert res.labels_created >= 6
    assert res.changed is True

    mock_client.create_namespace.assert_any_call(title="kubelab")
    mock_client.create_namespace.assert_any_call(title="personal")
    mock_client.create_namespace.assert_any_call(title="teledyne")

    mock_client.create_label.assert_any_call(title="agent:delegable", hex_color="#4a90e2")
    mock_client.create_label.assert_any_call(title="type:spec", hex_color="#2ecc71")


def test_reconciler_is_strictly_idempotent_when_resources_exist(mock_client: MagicMock) -> None:
    # State: all namespaces and labels already exist
    mock_client.get_namespaces.return_value = [
        {"id": 1, "title": "kubelab"},
        {"id": 2, "title": "personal"},
        {"id": 3, "title": "teledyne"},
    ]
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

    reconciler = VikunjaReconciler(client=mock_client)
    res = reconciler.reconcile()

    assert res.namespaces_created == 0
    assert res.labels_created == 0
    assert res.changed is False

    mock_client.create_namespace.assert_not_called()
    mock_client.create_label.assert_not_called()
