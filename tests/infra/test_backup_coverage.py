"""Infrastructure: does anything hold state on a node without being backed up? — BACKUP-044 AC6.

This is the half of AC6 that the static allow-list test cannot do, and the half that
carries the actual value.

`tests/test_backup_sources.py` checks that what `common.yaml` declares is complete and
well-formed. That can never catch the failure that matters, because **an allow-list
that only validates what it declares cannot report what it forgot**. A service added
to a node next month is invisible to it: nothing is malformed, nothing is missing from
its own list, and the backup silently does not cover the new thing.

So this test inverts the direction. It asks the *node* what it is holding, and fails
when something is neither declared as a backup source nor explicitly acknowledged as
not needing one.

WHY THAT IS NOT JUST AN EXCLUDE LIST AGAIN
------------------------------------------
`roles/backup` failed open: it enumerated volumes minus an exclude list, so anything
new was swept in (or, on a node with bind mounts, silently missed) and nobody was told.
`_ACKNOWLEDGED_UNBACKED` below fails **closed**: a newly appearing stateful path turns
this test red, and the only ways to green are to back it up or to write down why it
does not need backing up. The list is an acknowledgement record, not a filter — every
entry carries the reason it is safe to skip, and most trace to the ratified Tier 3
in #452.

REACHABILITY
------------
Two of the four covered nodes are `location: on-demand` (ADR-028), so they are off most
of the time. An unreachable node is SKIPPED, never failed — a test that goes red because
the homelab is powered down teaches people to ignore it, which is the same reasoning
`common.yaml` already applies to staging probes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from .fixtures import NodeInfo, node_ssh_run

pytestmark = pytest.mark.infra

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMON = yaml.safe_load((_REPO_ROOT / "infra" / "config" / "values" / "common.yaml").read_text())

# Paths that hold no state worth backing up. Every entry needs a reason; an entry
# without one is someone silencing the test rather than answering it.
_ACKNOWLEDGED_UNBACKED: dict[str, str] = {
    # Ratified Tier 3 (#452) — rebuildable in full, so a backup would be dead weight.
    "gravity.db": "Pi-hole blocklist, regenerated in full by `pihole -g`",
    "minio-data": "the backup destination itself; backing it up is circular",
    "loki-data": "log storage, ratified Tier 3",
    # Build and runtime caches. Rebuildable by definition, and large.
    "buildx_buildkit": "buildx builder state, a cache",
    "github_runner_toolcache": "GitHub Actions tool cache, re-downloaded on demand",
    "github_runner_data": "runner work directory, recreated per job",
    # Dead volumes from the pre-K3s era. Tracked for deletion in #1092, not backed up.
    "jekyll-staging": "dead pre-K3s volume (#1092)",
    "jekyll-production": "dead pre-K3s volume (#1092)",
    "monitoring_": "superseded by the K3s observability stack (#1092)",
    "n8n_": "superseded by the K3s n8n deployment (#1092)",
    "uptime-kuma_uptime_kuma_data": "the ORPHAN volume, frozen 2026-03-28 (#1092 instance 1)",
    # Found by THIS test on its first run, 2026-08-15 — a fourth orphan #1092 did not
    # know about. No Portainer container exists on the VPS at all; the volume has been
    # frozen since 2026-03-19, around the K3s cutover. Acknowledged here rather than
    # backed up, and filed as evidence on #1092 for deletion.
    "portainer_portainer_data": "orphan, no container since ~2026-03-19 (#1092 instance 4)",
    "headscale_headscale": "covered — matches the declared source name prefix",
}


def _declared_sources(node_name: str) -> list[dict[str, Any]]:
    return list(_COMMON.get("backup", {}).get("sources", {}).get(node_name, {}).values())


def _acknowledged(candidate: str) -> str | None:
    for marker, reason in _ACKNOWLEDGED_UNBACKED.items():
        if marker in candidate:
            return reason
    return None


class TestBackupCoverage:
    """Every stateful thing on a covered node is declared, or acknowledged as not needing it."""

    @pytest.mark.parametrize("node_name", ["beelink", "rpi3", "rpi4", "vps"])
    def test_no_undeclared_docker_volume(
        self, inventory: list[NodeInfo], node_name: str
    ) -> None:
        node = next((n for n in inventory if node_name in n.name), None)
        if node is None:
            pytest.skip(f"{node_name} is not in the inventory")

        probe = node_ssh_run(node, "docker volume ls --format '{{.Name}}'", timeout=20)
        if probe.returncode != 0:
            pytest.skip(f"{node_name} unreachable or has no Docker — powered off is normal here")

        declared = {s["volume"] for s in _declared_sources(node_name) if "volume" in s}
        undeclared: list[str] = []
        for volume in filter(None, (v.strip() for v in probe.stdout.splitlines())):
            if volume in declared or _acknowledged(volume):
                continue
            undeclared.append(volume)

        assert not undeclared, (
            f"{node_name} holds Docker volumes that are neither declared in "
            f"`backup.sources` nor acknowledged as not needing backup: {sorted(undeclared)}.\n"
            "Resolve it, do not silence it: either add the volume to backup.sources in "
            "common.yaml, or add it to _ACKNOWLEDGED_UNBACKED here WITH the reason it is "
            "safe to skip. This test exists because the allow-list cannot report what it "
            "was never told about."
        )

    @pytest.mark.parametrize("node_name", ["beelink", "rpi3", "rpi4", "vps"])
    def test_declared_sources_actually_exist(
        self, inventory: list[NodeInfo], node_name: str
    ) -> None:
        """The mirror image: a declared source that is not on the node backs up nothing.

        `restic backup` on a missing path fails loudly, but only at run time on a node
        that may be powered off for weeks. Catching it here means a typo or a moved
        service surfaces while someone is looking.
        """
        node = next((n for n in inventory if node_name in n.name), None)
        if node is None:
            pytest.skip(f"{node_name} is not in the inventory")

        sources = _declared_sources(node_name)
        if not sources:
            pytest.skip(f"{node_name} declares no backup sources yet")

        missing: list[str] = []
        for source in sources:
            if "path" in source:
                check = node_ssh_run(node, f"test -e {source['path']}", timeout=20)
                if check.returncode == 255:
                    pytest.skip(f"{node_name} unreachable — powered off is normal here")
                if check.returncode != 0:
                    missing.append(f"path {source['path']}")
            elif "volume" in source:
                check = node_ssh_run(
                    node, f"docker volume inspect {source['volume']} >/dev/null 2>&1", timeout=20
                )
                if check.returncode == 255:
                    pytest.skip(f"{node_name} unreachable — powered off is normal here")
                if check.returncode != 0:
                    missing.append(f"volume {source['volume']}")

        assert not missing, (
            f"{node_name} declares backup sources that do not exist on the node: {missing}. "
            "A declared source that is not there backs up nothing while the run reports success."
        )
