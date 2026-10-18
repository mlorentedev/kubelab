"""Vikunja platform reconciler: idempotently provisions projects, one team, shares and labels.

A Vikunja project is visible only to its owner and to whoever it is shared with.
Whoever creates it (here the account holding n8n's token) must not decide who
sees the board, so the projects a deployment declares are shared with one team
whose members are the human identities (#1701, APP-CONFIG-013).

Webhooks are deliberately not registered here: the one consumer,
`agent-dispatcher`, requires `headerAuth`, and Vikunja can only sign with an
HMAC, so a registered hook would answer 403 on every event.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from toolkit.core.logging import logger
from toolkit.features.vikunja_client import VikunjaClient, VikunjaError

#: Declared right -> Vikunja's permission integer (models.Permission in its swagger).
RIGHTS = {"read": 0, "write": 1, "admin": 2}

DEFAULT_LABELS = {
    "type:spec": "#2ecc71",
    "type:bug": "#e74c3c",
    "type:chore": "#95a5a6",
    "agent:delegable": "#4a90e2",
    "priority:P0": "#c0392b",
    "priority:P1": "#e67e22",
    "priority:P2": "#f1c40f",
    "priority:P3": "#3498db",
}

#: One colour for every `area:*` label: an area names where a task came from, and a colour per area
#: would make forty of them compete with the type and priority colours that carry meaning.
AREA_COLOR = "#7f8c8d"

#: The AREA segment of the spec `idPattern` (cli/internal/spec/spec.go): upper-case segments, digits allowed.
_AREA_SEGMENT = re.compile(r"^[A-Z]+[0-9]*(-[A-Z]+[0-9]*)*$")


class ReconcileError(Exception):
    """The declaration cannot be applied; nothing further was written."""


@dataclass(frozen=True)
class VikunjaDeclaration:
    """What `apps.services.core.vikunja` declares, with members already resolved to usernames."""

    projects: tuple[str, ...]
    team_name: str
    team_right: str
    members: tuple[str, ...]
    areas: tuple[str, ...] = ()


def _areas_from(vikunja: dict[str, Any]) -> tuple[str, ...]:
    areas = tuple(vikunja.get("labels", {}).get("areas", ()))
    for area in areas:
        if not isinstance(area, str) or not _AREA_SEGMENT.match(area):
            raise ReconcileError(f"labels.areas entry {area!r} is not an AREA segment (e.g. OPS, APP-CONFIG)")
    for area in sorted(set(areas)):
        if areas.count(area) > 1:
            raise ReconcileError(f"labels.areas lists {area!r} twice")
    return areas


def declaration_from_config(config: dict[str, Any]) -> VikunjaDeclaration:
    """Read the declaration from merged config; member keys resolve through `apps.auth.identities`."""
    apps = config["apps"]
    vikunja = apps["services"]["core"]["vikunja"]
    identities = apps["auth"]["identities"]
    team = vikunja["team"]
    try:
        members = tuple(identities[key] for key in team["members"])
    except KeyError as exc:
        raise ReconcileError(f"team member {exc} is not a key of apps.auth.identities") from exc
    return VikunjaDeclaration(
        projects=tuple(vikunja["projects"]),
        team_name=team["name"],
        team_right=team["right"],
        members=members,
        areas=_areas_from(vikunja),
    )


@dataclass(frozen=True)
class ReconcileResult:
    """Result of a Vikunja platform reconciliation run."""

    projects_created: int
    team_created: int
    members_added: int
    shares_changed: int
    labels_created: int

    @property
    def changed(self) -> bool:
        return (
            self.projects_created + self.team_created + self.members_added + self.shares_changed + self.labels_created
        ) > 0


class VikunjaReconciler:
    """Idempotently synchronizes the declared projects, team, shares and labels to Vikunja."""

    def __init__(self, client: VikunjaClient) -> None:
        self.client = client

    def reconcile(self, declaration: VikunjaDeclaration) -> ReconcileResult:
        """Run full platform reconciliation. Safe to re-run anytime (changed=0 on re-run)."""
        if declaration.team_right not in RIGHTS:
            raise ReconcileError(f"team right {declaration.team_right!r} is not one of {sorted(RIGHTS)}")

        project_ids, projects_created = self._reconcile_projects(declaration.projects)
        team_id, team_created, members_added = self._reconcile_team(declaration)
        shares_changed = self._reconcile_shares(project_ids, team_id, RIGHTS[declaration.team_right])
        labels_created = self._reconcile_labels(declaration.areas)

        result = ReconcileResult(
            projects_created=projects_created,
            team_created=team_created,
            members_added=members_added,
            shares_changed=shares_changed,
            labels_created=labels_created,
        )

        if result.changed:
            logger.info(
                f"Vikunja reconciled: {result.projects_created} projects, {result.team_created} team, "
                f"{result.members_added} members, {result.shares_changed} shares, {result.labels_created} labels."
            )
        else:
            logger.info("Vikunja already in desired state (changed=0).")

        return result

    def _reconcile_projects(self, desired: tuple[str, ...]) -> tuple[list[int], int]:
        # Archived projects count: a second board next to an archived one splits the work.
        existing = {p.get("title", "").lower(): p for p in self.client.get_projects(include_archived=True)}
        ids: list[int] = []
        created = 0

        for title in desired:
            project = existing.get(title.lower())
            if project is None:
                logger.info(f"Creating missing Vikunja project: {title}")
                project = self.client.create_project(title=title)
                created += 1
            ids.append(project["id"])

        return ids, created

    def _reconcile_team(self, declaration: VikunjaDeclaration) -> tuple[int, int, int]:
        teams = {t.get("name", "").lower(): t for t in self.client.get_teams()}
        team = teams.get(declaration.team_name.lower())
        created = 0
        if team is None:
            logger.info(f"Creating missing Vikunja team: {declaration.team_name}")
            team = self.client.create_team(name=declaration.team_name)
            created = 1
        team_id = team["id"]

        # Read the members after creating: the creator joins its own team, and adding it again errors.
        present = {m.get("username", "").lower() for m in self.client.get_team(team_id).get("members") or []}
        added = 0
        for username in declaration.members:
            if username.lower() in present:
                continue
            logger.info(f"Adding {username} to Vikunja team {declaration.team_name}")
            try:
                self.client.add_team_member(team_id=team_id, username=username)
            except VikunjaError as exc:
                raise ReconcileError(
                    f"cannot add {username!r} to team {declaration.team_name!r}: {exc}. "
                    "Vikunja creates an account on first SSO login; has that user signed in once?"
                ) from exc
            added += 1

        return team_id, created, added

    def _reconcile_shares(self, project_ids: list[int], team_id: int, permission: int) -> int:
        changed = 0
        for project_id in project_ids:
            shared = {t["id"]: t for t in self.client.get_project_teams(project_id)}
            current = shared.get(team_id)
            if current is None:
                logger.info(f"Sharing Vikunja project {project_id} with team {team_id} (permission {permission})")
                self.client.share_project_with_team(project_id=project_id, team_id=team_id, permission=permission)
                changed += 1
            elif current.get("permission") != permission:
                logger.info(
                    f"Correcting project {project_id} share: permission {current.get('permission')} -> {permission}"
                )
                self.client.update_project_team_permission(
                    project_id=project_id, team_id=team_id, permission=permission
                )
                changed += 1
        return changed

    def _reconcile_labels(self, areas: tuple[str, ...] = ()) -> int:
        existing = {lbl.get("title", ""): lbl for lbl in self.client.get_labels()}
        created = 0

        wanted = {**DEFAULT_LABELS, **{f"area:{area}": AREA_COLOR for area in areas}}
        for label_title, color in wanted.items():
            if label_title not in existing:
                logger.info(f"Creating missing Vikunja label: {label_title} ({color})")
                self.client.create_label(title=label_title, hex_color=color)
                created += 1

        return created
