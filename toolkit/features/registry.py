"""Docker Hub registry client + ephemeral-tag pruning (ADR-046).

The one place the project performs *authenticated* registry operations. The
read-only tag-existence check used by promotion lives in ``promotion.py``; this
module adds login/list/delete so the CI janitor can prune ephemeral tags.

Staging runs immutable ``sha-<short>`` tags (one per app per merge to master),
so they accumulate forever. ``prune`` keeps the N most recent per app (rollback
headroom) and deletes the rest, plus any leftover ``-rc.*`` (the RC scheme was
dropped — release-please is the sole semver authority). Prod runs immutable
semver and is never touched here.

The decision of *what* to delete is the pure ``select_stale_tags``; everything
else is I/O. That split keeps the policy unit-testable without a network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from toolkit.config.settings import PROJECT_ROOT
from toolkit.core.logging import logger
from toolkit.features import product_registry

_HUB = "https://hub.docker.com/v2"
SHA_TAG_PREFIX = "sha-"  # immutable per-commit staging tag scheme (ADR-046)
_RC_MARKER = "-rc."  # dropped scheme; any remaining are dead


@dataclass(frozen=True)
class TagInfo:
    """A registry tag and its last-push time (ISO8601 sorts chronologically)."""

    name: str
    last_updated: str


def select_stale_tags(
    tags: list[TagInfo],
    retention: int,
    protected: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    """Pure policy: which tag names to delete.

    Keep the ``retention`` most recent ``sha-*`` tags (newest first by
    ``last_updated``); the rest are stale. Every ``-rc.*`` tag is stale. Returns
    stale sha (oldest first) followed by rc tags.

    ``protected`` names are never returned — a sha pinned by a committed overlay
    (``values/<env>.yaml``) must survive even if it falls outside the retention
    window, or a pending build-once prod re-tag would lose its source (ADR-056).
    """
    if retention < 0:
        raise ValueError(f"retention must be >= 0, got {retention}")
    sha = sorted(
        (t for t in tags if t.name.startswith(SHA_TAG_PREFIX)),
        key=lambda t: t.last_updated,
        reverse=True,
    )
    stale_sha = [t.name for t in sha[retention:]]
    rc = [t.name for t in tags if _RC_MARKER in t.name]
    return [name for name in stale_sha + rc if name not in protected]


def tag_exists(registry: str, image_name: str, tag: str) -> bool | None:
    """Whether ``tag`` exists for an image. ``None`` (skip) for non-Docker-Hub registries.

    Anonymous read — used by promotion to refuse promoting a tag that does not
    exist (it would ``ImagePullBackOff``). Lives here so all registry access has
    one home; promotion no longer carries its own copy of the Docker Hub URL.
    """
    if not registry.startswith("docker.io/"):
        return None
    namespace = registry.split("/", 1)[1]
    url = f"{_HUB}/repositories/{namespace}/{image_name}/tags/{tag}"
    try:
        resp = httpx.get(url, timeout=15.0)
    except httpx.HTTPError as exc:
        logger.warning(f"Could not reach registry to verify tag ({exc}); skipping check")
        return None
    return resp.status_code == 200


class DockerHubClient:
    """Minimal authenticated Docker Hub v2 client (login, list, delete)."""

    def __init__(self, namespace: str, token: str | None = None) -> None:
        self.namespace = namespace
        self._token = token

    @classmethod
    def from_env(cls) -> DockerHubClient:
        """Build a client from ``DOCKERHUB_USERNAME``/``DOCKERHUB_TOKEN`` (CI secrets).

        On a workstation they come from SOPS, which `get_settings()` injects into
        the environment. Importing the toolkit no longer does that (TOOL-097), so
        build settings here when CI has not set them.
        """
        if not (os.environ.get("DOCKERHUB_USERNAME") and os.environ.get("DOCKERHUB_TOKEN")):
            from toolkit.config.settings import get_settings

            get_settings()
        user = os.environ.get("DOCKERHUB_USERNAME")
        password = os.environ.get("DOCKERHUB_TOKEN")
        if not user or not password:
            raise ValueError("DOCKERHUB_USERNAME and DOCKERHUB_TOKEN must be set in the environment")
        return cls(namespace=user, token=cls._login(user, password))

    @staticmethod
    def _login(user: str, password: str) -> str:
        resp = httpx.post(f"{_HUB}/users/login", json={"username": user, "password": password}, timeout=30.0)
        resp.raise_for_status()
        token = resp.json().get("token")
        if not token:
            raise ValueError("Docker Hub login returned no token")
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def list_tags(self, repo: str) -> list[TagInfo]:
        """All tags for ``<namespace>/<repo>``. A missing repo yields ``[]`` (nothing to prune)."""
        tags: list[TagInfo] = []
        url: str | None = f"{_HUB}/repositories/{self.namespace}/{repo}/tags/?page_size=100"
        while url:
            resp = httpx.get(url, headers=self._headers(), timeout=30.0)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            for result in data.get("results", []):
                name = result.get("name")
                if name:
                    tags.append(TagInfo(name=name, last_updated=result.get("last_updated") or ""))
            url = data.get("next")
        return tags

    def delete_tag(self, repo: str, tag: str) -> bool:
        """Delete one tag. 204 (deleted) and 404 (already gone) are both success."""
        resp = httpx.delete(
            f"{_HUB}/repositories/{self.namespace}/{repo}/tags/{tag}/",
            headers=self._headers(),
            timeout=30.0,
        )
        if resp.status_code in (204, 404):
            return True
        logger.warning(f"Failed to delete {repo}:{tag} (HTTP {resp.status_code})")
        return False


def image_repositories(
    apps: list[str], common: dict[str, Any] | None = None, registry: Path | None = None
) -> dict[str, str]:
    """The Docker Hub repository each app is deployed from (#2511), keyed by app.

    The same sources the generators read: ``derived_image`` for a contract-managed
    product, ``apps.platform.<app>.image_name`` for an in-tree one, and
    ``edge.errors.image_name`` for errors. A repository is a name under the hub
    namespace, so only the last segment of an image is kept.
    """
    if common is None:
        common = yaml.safe_load((PROJECT_ROOT / product_registry.COMMON_VALUES_RELPATH).read_text()) or {}
    repos: dict[str, str] = {}
    for app in apps:
        if app == "errors":
            name = ((common.get("edge") or {}).get("errors") or {}).get("image_name")
            key = "edge.errors.image_name"
        elif product_registry.product(app, registry).contract_managed:
            image = product_registry.derived_image(app, registry)
            name = image.removeprefix(f"{product_registry.platform_registry()}/")
            key = "the product registry"
        else:
            name = (((common.get("apps") or {}).get("platform") or {}).get(app) or {}).get("image_name")
            key = f"apps.platform.{app}.image_name"
        if not name:
            raise ValueError(f"No image repository for '{app}': {key} is not set")
        if "/" in name:
            # The hub client lists and deletes under its own namespace, so a name
            # that carries another one would prune the wrong repository.
            raise ValueError(f"Image repository for '{app}' from {key} is '{name}', not a bare name")
        repos[app] = name
    return repos


def prune(
    repos: dict[str, str],
    retention: int,
    dry_run: bool,
    client: DockerHubClient | None = None,
    protected: dict[str, set[str]] | None = None,
) -> int:
    """Prune stale tags in each app's repository (``repos`` maps app -> repo).

    ``protected`` maps app -> sha tags pinned by a committed overlay; those are
    never deleted (ADR-056 prune guard). Returns the count deleted (or, in
    ``dry_run``, that would be deleted).
    """
    client = client or DockerHubClient.from_env()
    protected = protected or {}
    total = 0
    for app, repo in repos.items():
        tags = client.list_tags(repo)
        keep = protected.get(app, set())
        stale = select_stale_tags(tags, retention, protected=keep)
        sha_count = sum(1 for t in tags if t.name.startswith(SHA_TAG_PREFIX))
        kept = min(sha_count, retention)
        if not stale:
            logger.info(f"{repo}: nothing to prune ({sha_count} sha-* tags, all {kept} retained)")
            continue
        deleted = 0
        for tag in stale:
            if dry_run:
                logger.info(f"{repo}: would delete {tag}")
                deleted += 1
            elif client.delete_tag(repo, tag):
                logger.info(f"{repo}: deleted {tag}")
                deleted += 1
        logger.info(f"{repo}: {deleted} deleted, kept {kept} of {sha_count} sha-*")
        total += deleted
    logger.success(f"Prune complete{' (dry-run)' if dry_run else ''}: {total} tag(s)")
    return total
