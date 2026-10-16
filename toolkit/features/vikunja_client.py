"""Vikunja REST API client for project, label, and webhook orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from toolkit.features.configuration import ConfigurationManager

#: Where the token n8n uses lives. The reconciler is the same caller class, so it
#: reads the same key rather than a second one.
TOKEN_SECRET_KEY = "apps.services.automation.n8n.vikunja_api_token"


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

    def get_projects(self) -> list[dict[str, Any]]:
        """Fetch all projects."""
        data = self._request("GET", "/projects")
        return data if isinstance(data, list) else []

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


def resolve_token(explicit: str, from_env: str, cm: ConfigurationManager) -> str:
    """The flag, then `VIKUNJA_API_TOKEN`, then SOPS. Never an empty token.

    `make sync-vikunja` passed neither flag nor variable and so authenticated as
    nobody (#1701). An empty result is an error here, because a request without a
    credential reads as the server's 401, which names the server and not the gap.
    """
    token = explicit or from_env or cm.get_secret_by_path(TOKEN_SECRET_KEY) or ""
    if not token:
        raise VikunjaError(
            f"no Vikunja API token: pass --token, set VIKUNJA_API_TOKEN, or set {TOKEN_SECRET_KEY} in SOPS"
        )
    return token
