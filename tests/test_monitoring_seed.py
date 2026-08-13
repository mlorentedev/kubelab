"""Structural validation for the Uptime Kuma seed (`infra/config/uptime-kuma/monitors.json`).

OBS-016: all 31 entries were migrated to carry an identity `key`, so a rename
is read as an edit rather than a delete + create (`monitoring_diff.py`'s
matching is marker-first with a name fallback). This guards the migration's
invariants going forward — a future edit to the seed must keep the same shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from toolkit.features.monitoring_diff import embed_key, extract_key

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "infra/config/uptime-kuma/monitors.json"


def _seed() -> list[dict]:
    return json.loads(SEED_PATH.read_text())


class TestSeedKeys:
    def test_every_monitor_has_a_key(self) -> None:
        seed = _seed()
        missing = [m["name"] for m in seed if not m.get("key")]
        assert not missing, f"monitors with no key: {missing}"

    def test_keys_are_unique(self) -> None:
        seed = _seed()
        keys = [m["key"] for m in seed]
        dupes = {k for k in keys if keys.count(k) > 1}
        assert not dupes, f"duplicate keys: {dupes}"

    def test_keys_round_trip_through_the_description_marker(self) -> None:
        """A key that can't round-trip through embed/extract can never be
        stamped onto a live monitor. Checked via the real functions
        `apply_monitors` uses, rather than a duplicated charset regex.
        """
        seed = _seed()
        for m in seed:
            key = m["key"]
            assert extract_key(embed_key("", key)) == key, f"key fails to round-trip: {key!r}"

    def test_key_is_the_first_field_in_each_entry(self) -> None:
        """So `monitoring-export`'s round-trip stays byte-stable — `_clean_monitor`
        always emits `key` first.
        """
        seed = _seed()
        for m in seed:
            assert next(iter(m)) == "key", f"'{m.get('name')}' does not have key as its first field"
