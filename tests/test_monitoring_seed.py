"""Structural validation for the Uptime Kuma seed (`infra/config/uptime-kuma/monitors.json`).

OBS-016: all 31 entries were migrated to carry an identity `key`, so a rename
is read as an edit rather than a delete + create (`monitoring_diff.py`'s
matching is marker-first with a name fallback). This guards the migration's
invariants going forward — a future edit to the seed must keep the same shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from toolkit.features.monitoring import _clean_monitor
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


class TestSeedCarriesNoPushToken:
    """The seed is public; a push token in it is a live credential (TOOL-038).

    `status.kubelab.live/api/push/<pushToken>` is publicly routed, so anyone
    holding a token can post "still alive" to the monitor whose entire job is to
    notice its absence. A leaked token does not weaken a dead-man's-switch, it
    inverts it. SOPS owns the value
    (`apps.services.observability.uptime_kuma.push_tokens.<key>`) and
    `hydrate_push_tokens` marries it to the seed in memory at apply time.
    """

    def test_no_entry_in_the_committed_seed_carries_a_token(self) -> None:
        offenders = [m.get("name") for m in _seed() if m.get("pushToken")]
        assert not offenders, (
            f"push token committed to a public repo in: {offenders}. "
            "Move it to SOPS under apps.services.observability.uptime_kuma.push_tokens"
        )

    def test_export_strips_the_token_it_reads_off_a_live_monitor(self) -> None:
        """The behavioural half of the guard.

        Asserting `pushToken not in _MONITOR_EXPORT_FIELDS` would pin the list;
        this pins what `monitoring-export` actually writes, which is the thing
        that would leak. `_clean_monitor` is given a live-shaped monitor —
        `get_monitors()` does return `pushToken` — and must drop it.
        """
        live = {
            "id": 7,
            "key": "ops-heartbeat",
            "name": "Backup heartbeat",
            "type": "push",
            "pushToken": "would-be-leaked",
            "description": "Prod PVC backup heartbeat.",
            "interval": 90000,
            "active": True,
        }
        assert "pushToken" not in _clean_monitor(live)

    def test_export_keeps_the_rest_of_a_push_monitor(self) -> None:
        """Stripping the token must not strip the monitor: the entry still has to
        round-trip, or `apply` would read it as deleted from the seed."""
        live = {
            "id": 7,
            "name": "Backup heartbeat",
            "type": "push",
            "pushToken": "would-be-leaked",
            "description": embed_key("Prod PVC backup heartbeat.", "ops-heartbeat"),
            "interval": 90000,
        }
        clean = _clean_monitor(live)
        assert clean["key"] == "ops-heartbeat"
        assert clean["type"] == "push"
        assert clean["interval"] == 90000
