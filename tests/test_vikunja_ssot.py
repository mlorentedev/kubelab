"""The Vikunja board, its team and its members are declared once, in common.yaml (#1701).

The declaration is read the way the reconciler reads it, with no SOPS: it holds
no secret. Every invariant below is one a human would otherwise discover when
the board turned up empty for them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

COMMON = Path(__file__).resolve().parents[1] / "infra" / "config" / "values" / "common.yaml"
RIGHTS = {"read", "write", "admin"}
#: Identities that are not people: a machine account and the PR reviewer. Neither is a team member.
NOT_HUMAN = {"machine", "reviewer"}


@pytest.fixture(scope="module")
def apps() -> dict:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]


@pytest.fixture(scope="module")
def vikunja(apps: dict) -> dict:
    return apps["services"]["core"]["vikunja"]


def test_projects_are_declared_and_unique(vikunja: dict) -> None:
    projects = vikunja.get("projects")
    assert isinstance(projects, list) and projects, "apps.services.core.vikunja.projects must list the board(s)"
    titles = [p.lower() for p in projects]
    assert len(titles) == len(set(titles)), f"project titles collide case-insensitively: {projects}"


def test_the_default_project_is_a_declared_project(vikunja: dict) -> None:
    declared = [p.lower() for p in vikunja.get("projects", [])]
    assert vikunja["default_project"].lower() in declared, (
        "forge events and Slack resolve default_project by title; if the reconciler does not "
        "create it, every create answers 422 or lands nowhere"
    )


def test_team_has_a_name_and_a_known_right(vikunja: dict) -> None:
    team = vikunja.get("team") or {}
    assert team.get("name"), "apps.services.core.vikunja.team.name is required"
    assert team.get("right") in RIGHTS, f"team.right must be one of {sorted(RIGHTS)}"


def test_team_members_are_human_identities(apps: dict, vikunja: dict) -> None:
    members = (vikunja.get("team") or {}).get("members")
    assert members, "a team with no members shares the board with nobody"
    identities = apps["auth"]["identities"]
    unknown = [m for m in members if m not in identities]
    assert not unknown, f"members must be keys of apps.auth.identities, not {unknown}"
    assert not set(members) & NOT_HUMAN, f"{sorted(set(members) & NOT_HUMAN)} are not people"
