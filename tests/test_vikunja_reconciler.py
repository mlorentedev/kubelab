"""Unit tests for the Vikunja reconciler: projects, one team, shares and labels (#1701).

The endpoints the client calls are pinned against the server's own swagger in
`test_vikunja_api_contract.py`, so a fake here cannot certify a removed one.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from toolkit.features.vikunja_client import VikunjaClient, VikunjaError
from toolkit.features.vikunja_reconciler import (
    DEFAULT_LABELS,
    ReconcileError,
    VikunjaDeclaration,
    VikunjaReconciler,
)

DECLARED = VikunjaDeclaration(
    projects=("Bitacora",),
    team_name="kubelab",
    team_right="write",
    members=("manu", "operator"),
)


@pytest.fixture
def client() -> MagicMock:
    """A board that already has everything declared; each test removes what it needs to create."""
    c = MagicMock(spec=VikunjaClient)
    c.get_projects.return_value = [{"id": 2, "title": "Bitacora"}]
    c.get_teams.return_value = [{"id": 5, "name": "kubelab"}]
    c.get_team.return_value = {"id": 5, "name": "kubelab", "members": [{"username": "manu"}, {"username": "operator"}]}
    c.get_project_teams.return_value = [{"id": 5, "permission": 1}]
    c.get_labels.return_value = [{"title": t} for t in DEFAULT_LABELS]
    return c


def _reconcile(client: MagicMock, declaration: VikunjaDeclaration = DECLARED):  # noqa: ANN202
    return VikunjaReconciler(client=client).reconcile(declaration)


def test_nothing_to_do_reports_changed_zero(client: MagicMock) -> None:
    res = _reconcile(client)
    assert res.changed is False
    client.create_project.assert_not_called()
    client.create_team.assert_not_called()
    client.add_team_member.assert_not_called()
    client.share_project_with_team.assert_not_called()


def test_creates_a_missing_project(client: MagicMock) -> None:
    client.get_projects.return_value = []
    client.create_project.return_value = {"id": 9, "title": "Bitacora"}
    client.get_project_teams.return_value = []

    res = _reconcile(client)

    client.create_project.assert_called_once_with(title="Bitacora")
    assert res.projects_created == 1
    # the project it just made is shared too: creating is not the end of the job
    client.share_project_with_team.assert_called_once_with(project_id=9, team_id=5, permission=1)


@pytest.mark.parametrize("existing_title", ["bitacora", "BITACORA", "Bitacora"])
def test_adopts_an_existing_project_by_title_instead_of_duplicating(client: MagicMock, existing_title: str) -> None:
    client.get_projects.return_value = [{"id": 2, "title": existing_title}]
    res = _reconcile(client)
    client.create_project.assert_not_called()
    assert res.projects_created == 0


def test_an_archived_project_is_still_the_project(client: MagicMock) -> None:
    """A second `Bitacora` next to an archived one would split the board."""
    client.get_projects.return_value = [{"id": 2, "title": "Bitacora", "is_archived": True}]
    _reconcile(client)
    client.create_project.assert_not_called()
    client.get_projects.assert_called_once_with(include_archived=True)


def test_creates_the_team_and_adds_only_members_it_does_not_have(client: MagicMock) -> None:
    """The token's owner joins a team it creates; adding that user again is an error, not a no-op."""
    client.get_teams.return_value = []
    client.create_team.return_value = {"id": 5, "name": "kubelab"}
    client.get_team.return_value = {"id": 5, "members": [{"username": "operator"}]}

    res = _reconcile(client)

    client.create_team.assert_called_once_with(name="kubelab")
    client.add_team_member.assert_called_once_with(team_id=5, username="manu")
    assert res.team_created == 1
    assert res.members_added == 1


def test_member_matching_ignores_case(client: MagicMock) -> None:
    client.get_team.return_value = {"id": 5, "members": [{"username": "Manu"}, {"username": "OPERATOR"}]}
    res = _reconcile(client)
    client.add_team_member.assert_not_called()
    assert res.members_added == 0


def test_a_member_who_never_signed_in_fails_closed_naming_them(client: MagicMock) -> None:
    client.get_team.return_value = {"id": 5, "members": [{"username": "operator"}]}
    client.add_team_member.side_effect = VikunjaError("Vikunja API error 404: user does not exist")

    with pytest.raises(ReconcileError, match="manu"):
        _reconcile(client)


def test_shares_a_project_that_is_not_shared_with_the_team(client: MagicMock) -> None:
    client.get_project_teams.return_value = []
    res = _reconcile(client)
    client.share_project_with_team.assert_called_once_with(project_id=2, team_id=5, permission=1)
    assert res.shares_changed == 1


def test_corrects_a_share_whose_right_drifted(client: MagicMock) -> None:
    client.get_project_teams.return_value = [{"id": 5, "permission": 0}]
    res = _reconcile(client)
    client.update_project_team_permission.assert_called_once_with(project_id=2, team_id=5, permission=1)
    client.share_project_with_team.assert_not_called()
    assert res.shares_changed == 1


@pytest.mark.parametrize(("right", "permission"), [("read", 0), ("write", 1), ("admin", 2)])
def test_the_declared_right_maps_to_vikunjas_permission(client: MagicMock, right: str, permission: int) -> None:
    client.get_project_teams.return_value = []
    declared = VikunjaDeclaration(("Bitacora",), "kubelab", right, ("manu",))
    client.get_team.return_value = {"id": 5, "members": [{"username": "manu"}]}
    _reconcile(client, declared)
    client.share_project_with_team.assert_called_once_with(project_id=2, team_id=5, permission=permission)


def test_an_unknown_right_is_refused_before_anything_is_written(client: MagicMock) -> None:
    with pytest.raises(ReconcileError, match="right"):
        _reconcile(client, VikunjaDeclaration(("Bitacora",), "kubelab", "owner", ("manu",)))
    client.create_project.assert_not_called()


def test_creates_missing_labels(client: MagicMock) -> None:
    client.get_labels.return_value = []
    res = _reconcile(client)
    assert res.labels_created == len(DEFAULT_LABELS)
    assert client.create_label.call_count == len(DEFAULT_LABELS)


def test_the_reconciler_never_registers_a_webhook(client: MagicMock) -> None:
    """agent-dispatcher requires headerAuth and Vikunja can only sign with HMAC (#1701, out of scope)."""
    client.get_projects.return_value = []
    client.create_project.return_value = {"id": 9, "title": "Bitacora"}
    _reconcile(client)
    client.create_webhook.assert_not_called()
    client.get_webhooks.assert_not_called()


def test_a_second_run_over_what_the_first_created_changes_nothing(client: MagicMock) -> None:
    """Idempotence: the state the first run leaves behind is the state the second finds."""
    client.get_projects.return_value = []
    client.get_teams.return_value = []
    client.get_labels.return_value = []
    client.get_project_teams.return_value = []
    client.create_project.return_value = {"id": 9, "title": "Bitacora"}
    client.create_team.return_value = {"id": 5, "name": "kubelab"}
    client.get_team.return_value = {"id": 5, "members": [{"username": "operator"}]}
    assert _reconcile(client).changed is True

    client.reset_mock()
    client.get_projects.return_value = [{"id": 9, "title": "Bitacora"}]
    client.get_teams.return_value = [{"id": 5, "name": "kubelab"}]
    client.get_labels.return_value = [{"title": t} for t in DEFAULT_LABELS]
    client.get_project_teams.return_value = [{"id": 5, "permission": 1}]
    client.get_team.return_value = {"id": 5, "members": [{"username": "manu"}, {"username": "operator"}]}
    assert _reconcile(client).changed is False
