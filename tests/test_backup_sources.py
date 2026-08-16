"""Unit tests for the backup source allow-list — BACKUP-044.

Pure SSOT assertions: NO SSH, no live node, no restic. Runs under ``make test``.

``roles/backup`` enumerated every Docker volume and subtracted an exclude list.
Measuring the fleet for #449 showed why that cannot work: on the Beelink, Gitea
is a **bind mount** and so is MinIO, while ``docker volume ls`` returns only
buildx caches and the runner toolcache. Pointed at that node, the old model
archives rebuildable junk, misses both services, and reports success. #1092's
AC3 inverts it to an allow-list; this file guards the declaration side.

The schema's rule is *declare the name we control, resolve the path at run time*,
which is why there are three source types rather than one path field. A literal
``/var/lib/docker/volumes/...`` belongs to Docker (``data-root`` is configurable)
and a PVC's on-disk path embeds a UUID that a recreated claim invalidates in
silence — both are paths another system owns, and declaring them is declaring
something that expires without warning.

**What is NOT here**, and it is the half that catches a real omission: a stateful
path that exists on disk on a covered node and is absent from this list. That
needs a live node, so it belongs in ``tests/infra/`` behind ``require_vpn``. AC6
is not closed by this file — an allow-list that only validates what it declares
cannot report what it forgot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

COMMON_YAML = Path(__file__).parent.parent / "infra" / "config" / "values" / "common.yaml"


@pytest.fixture(scope="module")
def common() -> dict[str, Any]:
    return yaml.safe_load(COMMON_YAML.read_text())


@pytest.fixture(scope="module")
def hosts(common: dict[str, Any]) -> dict[str, dict[str, Any]]:
    net = common["networking"]
    flat: dict[str, dict[str, Any]] = dict(net["nodes"])
    for key in ("vps", "aws"):
        if key in net:
            flat[key] = net[key]
    return flat

# The four nodes BACKUP-044 covers, from the ratified tiers (#452). Not the whole
# fleet: ace1/ace2/jetson hold no ratified Tier 1 or Tier 2 state.
COVERED_NODES = {"beelink", "rpi3", "rpi4", "vps"}

# Exactly one of these identifies a source, and which one is present IS the type.
# An explicit `type:` field would be a second source of truth inside every entry,
# always derivable from the rest — the redundancy this repo's SSOT rules exist to
# remove.
SOURCE_TYPES = {"path", "volume", "pvc"}


class TestBackupSources:
    """The allow-list: complete, well-formed, and naming things we control.

    The half NOT here is the one that catches an omission — a stateful path that
    exists on disk on a covered node and is absent from this list. That needs a
    live node, so it belongs in tests/infra/ behind require_vpn. AC6 is not
    closed by this class: an allow-list that only validates what it declares
    cannot report what it forgot.
    """

    @pytest.fixture(scope="module")
    def sources(self, common: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return common["backup"]["sources"]

    def test_all_ratified_nodes_are_covered(self, sources: dict[str, Any]) -> None:
        missing = sorted(COVERED_NODES - set(sources))
        assert not missing, (
            f"nodes holding ratified Tier 1/2 state with no declared source: {missing}. "
            "Measured 2026-08-15, one node of seven had any backup at all and its copy "
            "never left that node (#449)."
        )

    def test_source_nodes_exist_in_the_registry(
        self, sources: dict[str, Any], hosts: dict[str, dict[str, Any]]
    ) -> None:
        unknown = sorted(set(sources) - set(hosts))
        assert not unknown, f"backup.sources names hosts absent from the node registry: {unknown}"

    def test_each_source_declares_exactly_one_type(self, sources: dict[str, Any]) -> None:
        """The schema's central invariant.

        Zero types is an unusable entry. Two is ambiguous — and worse, it is the
        shape a half-finished migration between types leaves behind, which would
        otherwise sit there backing up whichever key the implementation happened
        to check first.
        """
        bad: list[str] = []
        for node, entries in sources.items():
            for name, entry in entries.items():
                found = SOURCE_TYPES & set(entry)
                if len(found) != 1:
                    bad.append(f"{node}.{name} declares {sorted(found) or 'none'}")
        assert not bad, f"every source needs exactly one of {sorted(SOURCE_TYPES)}: {bad}"

    def test_paths_are_absolute_and_names_are_not_paths(self, sources: dict[str, Any]) -> None:
        """A `volume:` holding a path means someone resolved it by hand.

        That is the failure this schema exists to prevent: a literal
        /var/lib/docker/volumes/... is Docker's to move, and a PVC path embeds a
        UUID that a recreated claim invalidates silently.
        """
        bad: list[str] = []
        for node, entries in sources.items():
            for name, entry in entries.items():
                if "path" in entry and not str(entry["path"]).startswith("/"):
                    bad.append(f"{node}.{name} path is not absolute: {entry['path']!r}")
                if "volume" in entry and "/" in str(entry["volume"]):
                    bad.append(f"{node}.{name} volume looks like a resolved path: {entry['volume']!r}")
                if "pvc" in entry and set(entry["pvc"]) != {"namespace", "claim"}:
                    bad.append(f"{node}.{name} pvc needs exactly namespace+claim: {entry['pvc']!r}")
        assert not bad, f"malformed sources: {bad}"

    def test_rpi3_names_the_live_volume_not_the_orphan(self, sources: dict[str, Any]) -> None:
        """#1092 instance 1 — the orphan is the larger, more canonical-looking one."""
        assert sources["rpi3"]["uptime_kuma"]["volume"] == "uptime_kuma_data", (
            "rpi3's Uptime Kuma source must name uptime_kuma_data. The orphan "
            "uptime-kuma_uptime_kuma_data is 26M against the live 22M and frozen since "
            "2026-03-28; backing it up would capture healthy-looking data the service "
            "does not read, and would pass any check asserting a non-empty backup exists."
        )

    def test_live_sqlite_databases_are_declared(self, sources: dict[str, Any]) -> None:
        """Every one of these was measured with a WAL larger and fresher than the db.

        headscale's was 1.35MB against a 118KB database and eight hours newer, so a
        file copy would have captured under 8% of the state while looking valid.
        """
        for node, name in (("beelink", "gitea"), ("rpi3", "uptime_kuma"),
                           ("rpi4", "pihole"), ("vps", "headscale")):
            assert sources[node][name].get("sqlite"), (
                f"{node}.{name} holds a live SQLite database but declares no `sqlite` key, "
                "so the capture step would copy the file instead of snapshotting it."
            )
