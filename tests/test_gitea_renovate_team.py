"""The Renovate run's write team: the third grant the reconciler converges (IDP-036 AC6).

The proposal declares the Renovate account "a member of each declared organization
with `write`, and owns nothing" (ADR-065 D1). `reconcilers` cannot carry that: its
grant lets members create repositories, and a repository a machine account creates is
one it owns. So the account gets its own team, write on every unit and no repository
creation, in every declared organization, and its membership is part of the grant
exactly as the reviewer's is: a converged team the account is not in lets Renovate
push to nothing.

Until `apps.auth.identities.renovate` is declared the reconciler plans nothing for it.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.test_gitea_repo_reconcile import (
    ALL_REFS_PRESENT,
    DECLARED,
    DECLARED_SETTINGS,
    N8N_HOOK_ONLY,
    converged_for,
    hooks_for,
    settings_for,
)
from tests.test_gitea_review_team import _ReadForge, converged_review_team, review_teams
from toolkit.features.gitea_client import TEAM_UNITS
from toolkit.features.gitea_repos import (
    READ_TEAM,
    RENOVATE_TEAM,
    WRITE_TEAM,
    ReconcilePlan,
    execute,
    format_plan,
    plan_reconcile,
    team_needs_convergence,
)

RENOVATE = "proteo"


def converged_renovate_team() -> dict[str, Any]:
    """What a correct `renovate` team reads back as, derived from `TEAM_UNITS`."""
    return {
        "id": 21,
        "name": RENOVATE_TEAM.name,
        "permission": "none",
        "can_create_org_repo": False,
        "units_map": {unit: RENOVATE_TEAM.permission for unit in TEAM_UNITS},
        "includes_all_repositories": True,
    }


def renovate_teams(members: tuple[str, ...] = (RENOVATE,)) -> dict[str, tuple[dict[str, Any] | None, tuple[str, ...]]]:
    return {org: (converged_renovate_team(), members) for org in DECLARED}


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
    return plan_reconcile(DECLARED, **kwargs, existing_repo_refs=ALL_REFS_PRESENT, existing_collaborators={})


# --------------------------------------------------------------------------- the grant


def test_the_renovate_grant_is_write_without_repository_creation() -> None:
    assert (RENOVATE_TEAM.name, RENOVATE_TEAM.permission, RENOVATE_TEAM.can_create_org_repo) == (
        "renovate",
        "write",
        False,
    )


def test_the_three_teams_have_distinct_names() -> None:
    """A shared name would make two grants fight over one team."""
    assert len({WRITE_TEAM.name, READ_TEAM.name, RENOVATE_TEAM.name}) == 3


def test_a_converged_renovate_team_needs_nothing() -> None:
    assert not team_needs_convergence(converged_renovate_team(), RENOVATE_TEAM, members=(RENOVATE,), member=RENOVATE)
    assert team_needs_convergence(None, RENOVATE_TEAM, members=(), member=RENOVATE)


@pytest.mark.parametrize(
    "drift",
    [
        {"can_create_org_repo": True},
        {"units_map": {unit: "read" for unit in TEAM_UNITS}},
        {"includes_all_repositories": False},
    ],
    ids=["can-create-repos", "narrowed-to-read", "covers-nothing"],
)
def test_a_renovate_team_off_its_grant_is_drift(drift: dict[str, Any]) -> None:
    team = {**converged_renovate_team(), **drift}
    assert team_needs_convergence(team, RENOVATE_TEAM, members=(RENOVATE,), member=RENOVATE)


def test_a_renovate_team_without_the_account_is_drift() -> None:
    assert team_needs_convergence(converged_renovate_team(), RENOVATE_TEAM, members=("someone-else",), member=RENOVATE)


# --------------------------------------------------------------------------- the plan


def test_a_declared_renovate_account_plans_every_organization_s_missing_team() -> None:
    plan = _plan(renovate=RENOVATE, existing_renovate_teams={org: (None, ()) for org in DECLARED})
    assert plan.renovate_teams_to_converge == tuple(sorted(DECLARED))
    assert plan.renovate == RENOVATE
    assert not plan.is_noop


def test_a_converged_renovate_team_with_its_member_is_a_noop() -> None:
    plan = _plan(renovate=RENOVATE, existing_renovate_teams=renovate_teams())
    assert plan.renovate_teams_to_converge == ()
    assert plan.is_noop


def test_a_renovate_team_missing_its_member_is_planned() -> None:
    plan = _plan(renovate=RENOVATE, existing_renovate_teams=renovate_teams(members=()))
    assert plan.renovate_teams_to_converge == tuple(sorted(DECLARED))
    assert not plan.is_noop


def test_an_undeclared_renovate_account_plans_nothing() -> None:
    """Before the identity row exists the reconciler behaves exactly as it did."""
    plan = _plan()
    assert plan.renovate_teams_to_converge == ()
    assert plan.renovate is None
    assert plan.is_noop


def test_a_declared_renovate_account_needs_every_declared_organization_read() -> None:
    partial = renovate_teams()
    partial.pop("teledyne")
    with pytest.raises(KeyError):
        _plan(renovate=RENOVATE, existing_renovate_teams=partial)


def test_a_renovate_account_without_its_reads_is_refused() -> None:
    with pytest.raises(ValueError, match="existing_renovate_teams"):
        _plan(renovate=RENOVATE)


def test_the_renovate_team_does_not_disturb_the_reviewer_team() -> None:
    """Each grant is planned from its own reads: a converged reviewer team stays quiet."""
    plan = _plan(
        reviewer="mentor",
        existing_review_teams=review_teams(),
        renovate=RENOVATE,
        existing_renovate_teams={org: (None, ()) for org in DECLARED},
    )
    assert plan.review_teams_to_converge == ()
    assert plan.renovate_teams_to_converge == tuple(sorted(DECLARED))
    assert converged_review_team()["name"] == READ_TEAM.name


def test_the_plan_names_the_renovate_team_and_its_member() -> None:
    teams = renovate_teams()
    teams["personal"] = (None, ())
    text = format_plan(_plan(renovate=RENOVATE, existing_renovate_teams=teams))
    assert f"personal/{RENOVATE_TEAM.name}" in text
    assert RENOVATE in text
    assert "teledyne/renovate" not in text


# --------------------------------------------------------------------------- execute


def _run(forge: _ReadForge, plan: ReconcilePlan) -> Any:
    return execute(
        plan,
        forge,  # type: ignore[arg-type]
        forge,  # type: ignore[arg-type]
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhooks=N8N_HOOK_ONLY,
    )


def test_execute_ensures_each_planned_renovate_team_with_the_account() -> None:
    forge = _ReadForge()
    report = _run(forge, ReconcilePlan(renovate_teams_to_converge=("personal",), renovate=RENOVATE))
    assert report.renovate_teams_ensured == ["personal"]
    assert ("create_team", ("personal", "renovate", "write", False)) in forge.calls
    assert ("add_team_member", (11, RENOVATE)) in forge.calls
    assert report.ok


def test_execute_records_a_renovate_team_it_could_not_converge() -> None:
    forge = _ReadForge({**converged_renovate_team(), "name": "renovate", "can_create_org_repo": True}, stuck=True)
    report = _run(forge, ReconcilePlan(renovate_teams_to_converge=("personal",), renovate=RENOVATE))
    assert report.renovate_teams_ensured == []
    assert [target for target, _ in report.failures] == ["team personal/renovate"]


def test_execute_without_a_renovate_plan_touches_no_renovate_team() -> None:
    forge = _ReadForge()
    report = _run(forge, ReconcilePlan())
    assert report.renovate_teams_ensured == []
    assert forge.calls == []


# --------------------------------------------------------------------------- the command


class _CliForge:
    """A forge holding the org `personal` and its `renovate` team, with `members` in it."""

    def __init__(self, members: tuple[str, ...]) -> None:
        self.members = members

    def list_orgs(self) -> set[str]:
        return {"personal"}

    def list_repos(self) -> dict[str, bool]:
        return {}

    def get_team(self, org: str, name: str) -> dict[str, Any] | None:
        return converged_renovate_team() if name == RENOVATE_TEAM.name else None

    def list_team_members(self, team_id: int) -> tuple[str, ...]:
        assert team_id == converged_renovate_team()["id"]
        return self.members

    def list_owned_repos(self, username: str) -> set[str]:
        return set()


def _read_through_the_command(
    monkeypatch: pytest.MonkeyPatch, identities: dict[str, str], members: tuple[str, ...]
) -> dict[str, Any]:
    """Run `gitea reconcile` plan-only and return the kwargs it handed `plan_reconcile`."""
    from typer.testing import CliRunner

    import toolkit.cli.services as cli
    import toolkit.features.gitea_repos as repos

    class _Config:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def get_merged_config(self) -> dict[str, object]:
            return {"apps": {"auth": {"identities": identities}}}

    seen: dict[str, Any] = {}

    def capture(*args: Any, **kwargs: Any) -> ReconcilePlan:
        seen.update(kwargs)
        return ReconcilePlan()

    monkeypatch.setattr(cli, "_gitea_clients", lambda env: (_CliForge(members), None, "hefesto", "https://forge.invalid"))
    monkeypatch.setattr(cli, "ConfigurationManager", _Config)
    monkeypatch.setattr(repos, "load_declaration", lambda merged: {"personal": []})
    monkeypatch.setattr(repos, "load_settings", lambda merged: None)
    monkeypatch.setattr(repos, "load_webhooks", lambda merged: ())
    monkeypatch.setattr(repos, "plan_reconcile", capture)

    result = CliRunner().invoke(cli.app, ["gitea", "reconcile"])
    assert result.exit_code == 0, result.output
    return seen


def test_the_command_reads_the_live_renovate_team_and_its_members_into_the_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _read_through_the_command(monkeypatch, {"machine": "hefesto", "renovate": RENOVATE}, members=(RENOVATE,))
    assert seen["renovate"] == RENOVATE
    team, members = seen["existing_renovate_teams"]["personal"]
    assert team["name"] == RENOVATE_TEAM.name
    assert members == (RENOVATE,)


def test_the_command_passes_no_renovate_reads_while_the_identity_is_undeclared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _read_through_the_command(monkeypatch, {"machine": "hefesto"}, members=())
    assert seen["renovate"] is None
    assert seen["existing_renovate_teams"] is None
