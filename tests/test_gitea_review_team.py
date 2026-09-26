"""The reviewer's read team: the second grant the reconciler converges (TOOL-080, AC5).

`reconcilers` was the only team the reconciler knew, and its grant was hardcoded:
write on every unit, `can_create_org_repo` on. The PR reviewer (`mentor`) needs the
opposite shape in every declared organization -- read on every unit, no repository
creation -- because read access is what contains it. Measured 2026-09-04 in a local
Gitea 1.25.5 (`specs/TOOL-080-forge-pr-reviewer/verification.md`): a read-team
member's token is refused labels, PR reviews and PR edits, and the same account in
a write team would be allowed all three.

So this grant is enforced in BOTH directions. `reconcilers` only ever widens; a
`reviewers` team someone widened to write is drift, and converging it narrows it
back, because for this team the narrowness is the property being declared.

Membership is part of the grant here, not an afterthought. A converged team the
reviewer is not in grants the reviewer nothing, so a plan that looked only at the
team's fields would report a forge that cannot review a single PR as converged.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.test_gitea_repo_reconcile import (
    DECLARED,
    DECLARED_SETTINGS,
    N8N_HOOK_ONLY,
    converged_for,
    hooks_for,
    settings_for,
)
from toolkit.features.gitea_client import TEAM_UNITS, GiteaClient
from toolkit.features.gitea_repos import (
    READ_TEAM,
    WRITE_TEAM,
    TeamPermissionError,
    ensure_team,
    format_plan,
    plan_reconcile,
    team_needs_convergence,
)

REVIEWER = "mentor"


def converged_review_team() -> dict[str, Any]:
    """What a correct `reviewers` team reads back as, derived from `TEAM_UNITS`."""
    return {
        "id": 11,
        "name": READ_TEAM.name,
        "permission": "none",
        "can_create_org_repo": False,
        "units_map": {unit: READ_TEAM.permission for unit in TEAM_UNITS},
        "includes_all_repositories": True,
    }


def review_teams(members: tuple[str, ...] = (REVIEWER,)) -> dict[str, tuple[dict[str, Any] | None, tuple[str, ...]]]:
    """Every declared organization, holding a converged review team with `members`."""
    return {org: (converged_review_team(), members) for org in DECLARED}


def _plan(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "existing_orgs": set(DECLARED),
        "existing_repos": {f"{o}/{s.name}": False for o, specs in DECLARED.items() for s in specs},
        "existing_teams": converged_for(DECLARED),
        "existing_repo_settings": settings_for(DECLARED),
        "declared_settings": DECLARED_SETTINGS,
        "existing_repo_hooks": hooks_for(DECLARED),
        "declared_webhooks": N8N_HOOK_ONLY,
    }
    kwargs.update(overrides)
    return plan_reconcile(DECLARED, **kwargs)


# --------------------------------------------------------------------------- the grant


def test_the_two_grants_are_the_shapes_the_lab_measured() -> None:
    assert (WRITE_TEAM.name, WRITE_TEAM.permission, WRITE_TEAM.can_create_org_repo) == ("reconcilers", "write", True)
    assert (READ_TEAM.name, READ_TEAM.permission, READ_TEAM.can_create_org_repo) == ("reviewers", "read", False)


def test_a_converged_review_team_needs_nothing() -> None:
    assert not team_needs_convergence(converged_review_team(), READ_TEAM, members=(REVIEWER,), member=REVIEWER)
    assert team_needs_convergence(None, READ_TEAM, members=(), member=REVIEWER)


@pytest.mark.parametrize(
    "drift",
    [
        {"units_map": {**{u: "read" for u in TEAM_UNITS}, "repo.code": "write"}},
        {"can_create_org_repo": True},
        {"includes_all_repositories": False},
    ],
    ids=["widened-to-write", "can-create-repos", "covers-nothing"],
)
def test_a_review_team_wider_or_narrower_than_read_is_drift(drift: dict[str, Any]) -> None:
    """Both directions, unlike `reconcilers`: a wider read team is not a bonus, it is the defect."""
    team = {**converged_review_team(), **drift}
    assert team_needs_convergence(team, READ_TEAM, members=(REVIEWER,), member=REVIEWER)


def test_a_review_team_without_the_reviewer_is_drift() -> None:
    assert team_needs_convergence(converged_review_team(), READ_TEAM, members=("someone-else",), member=REVIEWER)


def test_the_write_grant_is_unchanged_by_the_generalisation() -> None:
    """`reconcilers` still needs `can_create_org_repo` and write on every unit."""
    write_team = {
        "id": 7,
        "name": WRITE_TEAM.name,
        "permission": "none",
        "can_create_org_repo": True,
        "units_map": {unit: "write" for unit in TEAM_UNITS},
        "includes_all_repositories": True,
    }
    assert not team_needs_convergence(write_team)
    assert team_needs_convergence({**write_team, "can_create_org_repo": False})


# --------------------------------------------------------------------------- the payload


class _CapturingClient(GiteaClient):
    def __init__(self) -> None:
        super().__init__("https://forge.invalid", token="unused")
        self.sent: list[tuple[str, str, dict[str, Any]]] = []

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        self.sent.append((method, endpoint, kwargs.get("json") or {}))
        return {}


@pytest.mark.parametrize("call", ["create", "edit"])
def test_the_read_payload_grants_read_and_no_repository_creation(call: str) -> None:
    client = _CapturingClient()
    if call == "create":
        client.create_team("personal", READ_TEAM.name, READ_TEAM.permission, can_create_org_repo=False)
    else:
        client.edit_team(11, READ_TEAM.name, READ_TEAM.permission, can_create_org_repo=False)
    _, _, body = client.sent[0]
    assert body["can_create_org_repo"] is False
    assert body["units_map"] == {unit: "read" for unit in TEAM_UNITS}
    assert body["includes_all_repositories"] is True


def test_the_write_payload_still_creates_repositories_by_default() -> None:
    client = _CapturingClient()
    client.create_team("personal", WRITE_TEAM.name, WRITE_TEAM.permission)
    assert client.sent[0][2]["can_create_org_repo"] is True


def test_team_members_are_read_across_every_page() -> None:
    """Review of #1832: Gitea pages this listing, so a reviewer on page two must still be found."""
    from toolkit.features.gitea_client import PAGE_SIZE

    first = [{"login": f"user-{i}", "id": i} for i in range(PAGE_SIZE)]
    pages = [first, [{"login": "mentor", "id": 999}]]

    class _Members(_CapturingClient):
        def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
            super()._request(method, endpoint, **kwargs)
            return pages.pop(0)

    client = _Members()
    members = client.list_team_members(11)
    assert "mentor" in members and len(members) == PAGE_SIZE + 1
    assert all(endpoint.startswith("/teams/11/members?") for _, endpoint, _ in client.sent)


# --------------------------------------------------------------------------- ensure_team


class _ReadForge:
    """A forge that reads a team back with whatever grant it was last sent.

    `permission` reads back `none`, as on real Gitea 1.25 whenever the grant lives per
    unit. `stuck` models a PATCH that is accepted and changes nothing.
    """

    def __init__(self, team: dict[str, Any] | None = None, *, stuck: bool = False) -> None:
        self.team = team
        self.stuck = stuck
        self.calls: list[tuple[str, Any]] = []

    def get_team(self, org: str, name: str) -> dict[str, Any] | None:
        return self.team if self.team and self.team["name"] == name else None

    def _apply(self, name: str, permission: str, can_create_org_repo: bool) -> dict[str, Any]:
        self.team = {
            "id": 11,
            "name": name,
            "permission": "none",
            "can_create_org_repo": can_create_org_repo,
            "units_map": {unit: permission for unit in TEAM_UNITS},
            "includes_all_repositories": True,
        }
        return self.team

    def create_team(self, org: str, name: str, permission: str, *, can_create_org_repo: bool = True) -> dict[str, Any]:
        self.calls.append(("create_team", (org, name, permission, can_create_org_repo)))
        return self._apply(name, permission, can_create_org_repo)

    def edit_team(
        self, team_id: int, name: str, permission: str, *, can_create_org_repo: bool = True
    ) -> dict[str, Any]:
        self.calls.append(("edit_team", (team_id, name, permission, can_create_org_repo)))
        if self.stuck:
            assert self.team is not None
            return self.team
        return self._apply(name, permission, can_create_org_repo)

    def add_team_member(self, team_id: int, username: str) -> dict[str, Any]:
        self.calls.append(("add_team_member", (team_id, username)))
        return {}


def test_ensure_team_creates_the_read_team_and_adds_the_reviewer() -> None:
    forge = _ReadForge()
    team = ensure_team(forge, "personal", member=REVIEWER, grant=READ_TEAM)  # type: ignore[arg-type]
    assert ("create_team", ("personal", "reviewers", "read", False)) in forge.calls
    assert ("add_team_member", (11, REVIEWER)) in forge.calls
    assert team["can_create_org_repo"] is False


def test_ensure_team_narrows_a_review_team_someone_widened() -> None:
    widened = {**converged_review_team(), "units_map": {u: "write" for u in TEAM_UNITS}, "can_create_org_repo": True}
    forge = _ReadForge(widened)
    team = ensure_team(forge, "personal", member=REVIEWER, grant=READ_TEAM)  # type: ignore[arg-type]
    assert ("edit_team", (11, "reviewers", "read", False)) in forge.calls
    assert team["units_map"]["repo.code"] == "read"


def test_ensure_team_refuses_a_review_team_that_stays_able_to_create_repositories() -> None:
    """The post-condition, reached only when the repair did not take."""
    forge = _ReadForge({**converged_review_team(), "can_create_org_repo": True}, stuck=True)
    with pytest.raises(TeamPermissionError, match="can_create_org_repo"):
        ensure_team(forge, "personal", member=REVIEWER, grant=READ_TEAM)  # type: ignore[arg-type]


def test_ensure_team_refuses_a_review_team_that_stays_write() -> None:
    stuck = {**converged_review_team(), "units_map": {u: "write" for u in TEAM_UNITS}}
    forge = _ReadForge(stuck, stuck=True)
    with pytest.raises(TeamPermissionError, match="repo.code"):
        ensure_team(forge, "personal", member=REVIEWER, grant=READ_TEAM)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- the plan


def test_a_declared_reviewer_puts_every_organization_s_missing_team_in_the_plan() -> None:
    """Whole forge, `teledyne/` included (Manu, 2026-09-24), and `kubelab/` while it is empty."""
    plan = _plan(reviewer=REVIEWER, existing_review_teams={org: (None, ()) for org in DECLARED})
    assert plan.review_teams_to_converge == tuple(sorted(DECLARED))
    assert not plan.is_noop


def test_a_converged_review_team_with_its_member_is_a_noop() -> None:
    plan = _plan(reviewer=REVIEWER, existing_review_teams=review_teams())
    assert plan.review_teams_to_converge == ()
    assert plan.is_noop


def test_a_review_team_missing_its_member_is_planned() -> None:
    plan = _plan(reviewer=REVIEWER, existing_review_teams=review_teams(members=()))
    assert plan.review_teams_to_converge == tuple(sorted(DECLARED))


def test_no_declared_reviewer_plans_no_review_team() -> None:
    """Before the identity row exists, the reconciler behaves exactly as it did."""
    plan = _plan()
    assert plan.review_teams_to_converge == ()
    assert plan.is_noop


def test_a_declared_reviewer_needs_every_declared_organization_read() -> None:
    """Complete or loud: an organization missing from the reads is not "fine"."""
    partial = review_teams()
    partial.pop("teledyne")
    with pytest.raises(KeyError):
        _plan(reviewer=REVIEWER, existing_review_teams=partial)


def test_a_reviewer_without_its_reads_is_refused() -> None:
    with pytest.raises(ValueError, match="existing_review_teams"):
        _plan(reviewer=REVIEWER)


def test_the_plan_names_the_review_team_and_its_member() -> None:
    teams = review_teams()
    teams["personal"] = (None, ())
    text = format_plan(_plan(reviewer=REVIEWER, existing_review_teams=teams))
    assert "personal/reviewers" in text
    assert REVIEWER in text


# --------------------------------------------------------------------------- execute


def test_execute_ensures_each_planned_review_team_with_the_reviewer() -> None:
    from toolkit.features.gitea_repos import ReconcilePlan, execute

    forge = _ReadForge()
    plan = ReconcilePlan(review_teams_to_converge=("personal",), reviewer=REVIEWER)
    report = execute(
        plan,
        forge,  # type: ignore[arg-type]
        forge,  # type: ignore[arg-type]
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhooks=N8N_HOOK_ONLY,
    )
    assert report.review_teams_ensured == ["personal"]
    assert ("create_team", ("personal", "reviewers", "read", False)) in forge.calls
    assert ("add_team_member", (11, REVIEWER)) in forge.calls
    assert report.ok


def test_execute_records_a_review_team_it_could_not_converge() -> None:
    from toolkit.features.gitea_repos import ReconcilePlan, execute

    forge = _ReadForge({**converged_review_team(), "can_create_org_repo": True}, stuck=True)
    plan = ReconcilePlan(review_teams_to_converge=("personal",), reviewer=REVIEWER)
    report = execute(
        plan,
        forge,  # type: ignore[arg-type]
        forge,  # type: ignore[arg-type]
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhooks=N8N_HOOK_ONLY,
    )
    assert report.review_teams_ensured == []
    assert [target for target, _ in report.failures] == ["team personal/reviewers"]
