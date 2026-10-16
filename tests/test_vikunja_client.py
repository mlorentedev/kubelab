"""Unit tests for Vikunja REST API client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from toolkit.features.vikunja_client import PAGE_SIZE, VikunjaClient, VikunjaError


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


def _ok(payload: object, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = status
    resp.content = b"x"
    resp.json.return_value = payload
    return resp


def test_list_calls_read_every_page(client: VikunjaClient) -> None:
    """A single page silently hides every project past the first 50."""
    full_page = [{"id": i, "title": f"p{i}"} for i in range(PAGE_SIZE)]
    client.session.request.side_effect = [_ok(full_page), _ok([{"id": 99, "title": "last"}])]

    projects = client.get_projects(include_archived=True)

    assert len(projects) == PAGE_SIZE + 1
    pages = [c.kwargs["params"]["page"] for c in client.session.request.call_args_list]
    assert pages == [1, 2]
    assert client.session.request.call_args_list[0].kwargs["params"]["is_archived"] == "true"


def test_share_project_with_team_sends_team_id_and_permission(client: VikunjaClient) -> None:
    client.session.request.return_value = _ok({"team_id": 5, "permission": 1}, 201)

    client.share_project_with_team(project_id=2, team_id=5, permission=1)

    client.session.request.assert_called_once_with(
        "PUT",
        "https://tasks.kubelab.live/api/v1/projects/2/teams",
        json={"team_id": 5, "permission": 1},
        headers=client._headers(),
        timeout=10,
    )


def test_add_team_member_sends_the_username(client: VikunjaClient) -> None:
    client.session.request.return_value = _ok({"username": "manu"}, 201)

    client.add_team_member(team_id=5, username="manu")

    client.session.request.assert_called_once_with(
        "PUT",
        "https://tasks.kubelab.live/api/v1/teams/5/members",
        json={"username": "manu"},
        headers=client._headers(),
        timeout=10,
    )


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
        client.get_teams()
