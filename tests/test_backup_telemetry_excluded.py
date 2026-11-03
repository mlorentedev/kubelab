"""Telemetry and rebuildable indexes stay out of the offsite backup (#3035).

Each snapshot of a SQLite file under constant write re-stores a large part of it,
whatever the gap (lesson-700). Pi-hole's query history alone was ~31 MB a
snapshot, nearly all of rpi4's R2 growth, and it has no restore value. The lists
Pi-hole builds from live in `gravity.db`, so that is the database captured.
"""

from __future__ import annotations

import pathlib

import yaml

COMMON = pathlib.Path(__file__).resolve().parent.parent / "infra" / "config" / "values" / "common.yaml"
SOURCES = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["backup"]["sources"]


def test_pihole_captures_its_lists_and_not_its_query_history() -> None:
    pihole = SOURCES["rpi4"]["pihole"]
    assert pihole["sqlite"] == "gravity.db"
    for path in ("pihole-FTL.db", "pihole-FTL.db-wal", "pihole-FTL.db-shm"):
        assert path in pihole.get("exclude", {}), f"{path} would be copied raw into every snapshot"


def test_gitea_leaves_out_its_search_indexes_and_keeps_its_database() -> None:
    gitea = SOURCES["beelink"]["gitea"]
    assert gitea["sqlite"] == "gitea/gitea.db"
    assert "gitea/indexers" in gitea.get("exclude", {})
