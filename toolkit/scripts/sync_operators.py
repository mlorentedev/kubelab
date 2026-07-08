"""Refresh vendored cluster_bootstrap operator manifests from their SSOT-pinned version.

For each ``cluster_bootstrap`` entry (common.yaml) that declares both a ``version`` and a
``source`` (``{repo, asset}``), re-download the pinned GitHub release asset to the entry's
``manifest`` path via ``gh release download``. Config entries with no version/source (e.g.
coredns-custom) are skipped. Mirrors ``sync_k8s_images``: the version pin lives in the SSOT;
this just materialises the vendored file deterministically (TOOL-009 T6 / ADR-047).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

from toolkit.config.settings import settings
from toolkit.core.logging import logger


def _entries() -> list[dict[str, Any]]:
    common = settings.project_root / "infra/config/values/common.yaml"
    with open(common, encoding="utf-8") as f:
        return yaml.safe_load(f).get("cluster_bootstrap", []) or []


def _versioned(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entries that can be refreshed: those with both a version and a source."""
    return [e for e in entries if e.get("version") and e.get("source")]


def output_files() -> list[Path]:
    """Vendored manifest paths this sync manages (used by the ``--check`` drift mode)."""
    return [settings.project_root / e["manifest"] for e in _versioned(_entries())]


def main() -> int:
    entries = _entries()
    versioned = _versioned(entries)
    skipped = [e["name"] for e in entries if e not in versioned]
    if skipped:
        logger.info(f"sync-operators: skipping non-versioned entries: {', '.join(skipped)}")
    if not versioned:
        logger.warning("sync-operators: no versioned operators with a `source` declared")
        return 0

    rc = 0
    for entry in versioned:
        name = entry["name"]
        version = str(entry["version"])
        repo = entry["source"]["repo"]
        asset = entry["source"]["asset"]
        dest = settings.project_root / entry["manifest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"sync-operators: {name} {version} <- {repo}:{asset}")
        result = subprocess.run(
            [
                "gh",
                "release",
                "download",
                version,
                "--repo",
                repo,
                "--pattern",
                asset,
                "--output",
                str(dest),
                "--clobber",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.error(f"sync-operators: {name} failed: {(result.stderr or '').strip()}")
            rc = 1
            continue
        logger.success(f"sync-operators: {name} -> {entry['manifest']}")
    return rc
