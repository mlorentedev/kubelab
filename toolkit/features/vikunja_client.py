"""Vikunja REST API client for project, team, label, and webhook orchestration."""

from __future__ import annotations

from typing import Any

import requests

#: Vikunja's default max items per page; asking for more silently returns this many.
PAGE_SIZE = 50


class VikunjaError(Exception):
    """Raised when Vikunja API returns an error response."""


class VikunjaClient:
    """Synchronous HTTP client for Vikunja REST API v1."""

    def __init__(self, base_url: str, api_token: str, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault("headers", self._headers())
        kwargs.setdefault("timeout", self.timeout)

        resp = self.session.request(method, url, **kwargs)
        if not resp.ok:
            raise VikunjaError(f"Vikunja API error {resp.status_code}: {resp.text}")

        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def _get_all(self, endpoint: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Read every page of a list endpoint; a single page silently hides the rest."""
        items: list[dict[str, Any]] = []
        for page in range(1, 1000):
            data = self._request("GET", endpoint, params={**(params or {}), "page": page, "per_page": PAGE_SIZE})
            batch = data if isinstance(data, list) else []
            items.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        return items

    def get_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        """Fetch every project the token's owner can see."""
        return self._get_all("/projects", {"is_archived": str(include_archived).lower()})

    def create_project(self, title: str) -> dict[str, Any]:
        """Create a top-level project owned by the token's owner."""
        return self._request("PUT", "/projects", json={"title": title})

    def get_teams(self) -> list[dict[str, Any]]:
        """Fetch the teams the token's owner belongs to."""
        return self._get_all("/teams")

    def create_team(self, name: str) -> dict[str, Any]:
        """Create a team; its creator joins it as an admin."""
        return self._request("PUT", "/teams", json={"name": name})

    def get_team(self, team_id: int) -> dict[str, Any]:
        """Fetch one team with its members."""
        return self._request("GET", f"/teams/{team_id}")

    def add_team_member(self, team_id: int, username: str) -> dict[str, Any]:
        """Add an existing account to a team by username."""
        return self._request("PUT", f"/teams/{team_id}/members", json={"username": username})

    def get_project_teams(self, project_id: int) -> list[dict[str, Any]]:
        """Fetch the teams a project is shared with, each carrying its permission."""
        return self._get_all(f"/projects/{project_id}/teams")

    def share_project_with_team(self, project_id: int, team_id: int, permission: int) -> dict[str, Any]:
        """Share a project with a team (permission 0 read, 1 write, 2 admin)."""
        return self._request(
            "PUT", f"/projects/{project_id}/teams", json={"team_id": team_id, "permission": permission}
        )

    def update_project_team_permission(self, project_id: int, team_id: int, permission: int) -> dict[str, Any]:
        """Change the permission of an existing project-team share."""
        return self._request("POST", f"/projects/{project_id}/teams/{team_id}", json={"permission": permission})

    def get_labels(self) -> list[dict[str, Any]]:
        """Fetch all task labels."""
        data = self._request("GET", "/labels")
        return data if isinstance(data, list) else []

    def create_label(self, title: str, hex_color: str = "") -> dict[str, Any]:
        """Create a new label."""
        payload: dict[str, Any] = {"title": title}
        if hex_color:
            payload["hex_color"] = hex_color
        return self._request("PUT", "/labels", json=payload)

    def get_webhooks(self, project_id: int) -> list[dict[str, Any]]:
        """Fetch all webhooks registered on a project."""
        data = self._request("GET", f"/projects/{project_id}/webhooks")
        return data if isinstance(data, list) else []

    def create_webhook(
        self,
        project_id: int,
        target_url: str,
        events: list[str],
        secret: str = "",
    ) -> dict[str, Any]:
        """Register a new webhook on a project."""
        payload: dict[str, Any] = {
            "target_url": target_url,
            "events": events,
        }
        if secret:
            payload["secret"] = secret
        return self._request("PUT", f"/projects/{project_id}/webhooks", json=payload)

    def update_task(self, task_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Apply a granular patch/update to a task."""
        return self._request("POST", f"/tasks/{task_id}", json=updates)

    def add_task_comment(self, task_id: int, comment: str) -> dict[str, Any]:
        """Add a comment to an existing task."""
        return self._request("PUT", f"/tasks/{task_id}/comments", json={"comment": comment})
