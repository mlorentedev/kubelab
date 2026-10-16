"""Unit tests for Vikunja REST API client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from toolkit.features.vikunja_client import VikunjaClient, VikunjaError


@pytest.fixture
def client() -> VikunjaClient:
    c = VikunjaClient(base_url="https://tasks.kubelab.live/api/v1", api_token="test-api-token")
    c.session = MagicMock()
    return c


def test_headers_include_bearer_token() -> None:
    c = VikunjaClient(base_url="https://tasks.kubelab.live/api/v1", api_token="test-api-token")
    headers = c._headers()
    assert headers["Authorization"] == "Bearer test-api-token"
    assert headers["Content-Type"] == "application/json"


def test_get_labels_returns_list(client: VikunjaClient) -> None:
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.content = b'[{"id": 1, "title": "type:spec"}]'
    mock_resp.json.return_value = [{"id": 1, "title": "type:spec"}, {"id": 2, "title": "priority:P0"}]
    client.session.request.return_value = mock_resp

    labels = client.get_labels()
    assert len(labels) == 2
    assert labels[0]["title"] == "type:spec"


def test_create_label_success(client: VikunjaClient) -> None:
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 201
    mock_resp.content = b'{"id": 10, "title": "agent:delegable"}'
    mock_resp.json.return_value = {"id": 10, "title": "agent:delegable", "hex_color": "4a90e2"}
    client.session.request.return_value = mock_resp

    res = client.create_label(title="agent:delegable", hex_color="4a90e2")
    assert res["id"] == 10
    assert res["title"] == "agent:delegable"


def test_patch_task_uses_granular_update(client: VikunjaClient) -> None:
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.content = b'{"id": 42, "done": true}'
    mock_resp.json.return_value = {"id": 42, "done": True}
    client.session.request.return_value = mock_resp

    res = client.update_task(task_id=42, updates={"done": True})
    assert res["done"] is True
    client.session.request.assert_called_once_with(
        "POST",
        "https://tasks.kubelab.live/api/v1/tasks/42",
        json={"done": True},
        headers=client._headers(),
        timeout=10,
    )


def test_add_task_comment(client: VikunjaClient) -> None:
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 201
    mock_resp.content = b'{"id": 99, "comment": "PR opened"}'
    mock_resp.json.return_value = {"id": 99, "comment": "PR opened"}
    client.session.request.return_value = mock_resp

    res = client.add_task_comment(task_id=42, comment="PR opened")
    assert res["id"] == 99
    client.session.request.assert_called_once_with(
        "PUT",
        "https://tasks.kubelab.live/api/v1/tasks/42/comments",
        json={"comment": "PR opened"},
        headers=client._headers(),
        timeout=10,
    )


def test_api_error_raises_vikunja_error(client: VikunjaClient) -> None:
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    client.session.request.return_value = mock_resp

    with pytest.raises(VikunjaError, match="Vikunja API error 401"):
        client.get_projects()


class _Config:
    def __init__(self, value: str | None) -> None:
        self.value = value
        self.asked: list[str] = []

    def get_secret_by_path(self, path: str) -> str | None:
        self.asked.append(path)
        return self.value


def test_the_token_comes_from_the_flag_then_the_environment_then_sops() -> None:
    from toolkit.features.vikunja_client import resolve_token

    cm = _Config("from-sops")
    assert resolve_token("flag", "env", cm) == "flag"  # type: ignore[arg-type]
    assert resolve_token("", "env", cm) == "env"  # type: ignore[arg-type]
    assert cm.asked == [], "SOPS is only read when nothing else supplied a token"
    assert resolve_token("", "", cm) == "from-sops"  # type: ignore[arg-type]
    assert cm.asked == ["apps.services.automation.n8n.vikunja_api_token"]


def test_no_token_anywhere_is_an_error_not_an_anonymous_request() -> None:
    """`make sync-vikunja` authenticated as nobody for as long as it existed (#1701)."""
    from toolkit.features.vikunja_client import resolve_token

    with pytest.raises(VikunjaError, match="no Vikunja API token"):
        resolve_token("", "", _Config(None))  # type: ignore[arg-type]
