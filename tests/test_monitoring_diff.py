"""Unit tests for the declarative monitor diff (OPS-016, #962/#925).

These exercise the DECISION half of `monitoring-apply` with no live Uptime Kuma
in sight. That separation is the point: the current `apply_monitors` interleaves
deciding and doing in one loop, which is why it has never had a test and why its
delete-everything behaviour went unnoticed for 31 monitors' worth of history.

Identity model under test: each seed entry carries an immutable `key`, persisted
into the live instance inside `description` as a marker, because Uptime Kuma
stores only its own fields and has nowhere to keep a custom one. Matching is
marker-first with a name fallback, so the first sync against an unmarked
instance adopts the existing monitors by name instead of deleting them.
"""

from toolkit.features.monitoring_diff import (
    diff_monitors,
    embed_key,
    extract_key,
    strip_key,
)


class TestKeyMarker:
    """The key survives a round-trip through `description` and stays invisible."""

    def test_embed_then_extract_returns_the_key(self):
        desc = embed_key("Beelink metrics agent.", "glances-bee")
        assert extract_key(desc) == "glances-bee"

    def test_strip_restores_the_human_text_exactly(self):
        original = "Beelink metrics agent."
        assert strip_key(embed_key(original, "glances-bee")) == original

    def test_embed_is_idempotent(self):
        # Re-applying must not stack markers: apply runs on every sync.
        once = embed_key("Agent.", "k1")
        assert embed_key(once, "k1") == once

    def test_embed_replaces_a_stale_key_rather_than_appending(self):
        assert extract_key(embed_key(embed_key("Agent.", "old"), "new")) == "new"

    def test_extract_returns_none_when_unmarked(self):
        assert extract_key("Just a description.") is None
        assert extract_key("") is None
        assert extract_key(None) is None

    def test_strip_is_safe_on_unmarked_text(self):
        assert strip_key("Just a description.") == "Just a description."


class TestDiffMatching:
    """Marker-first, name-fallback. The fallback is what makes migration free."""

    def test_matches_by_marker_even_when_the_name_changed(self):
        seed = [{"key": "glances-bee", "name": "Glances Beelink (renamed)"}]
        live = [{"id": 7, "name": "Glances Beelink", "description": embed_key("", "glances-bee")}]

        create, edit, delete = diff_monitors(seed, live)

        assert create == []
        assert delete == []
        assert [m["id"] for m in edit] == [7], "a rename must edit, never delete+create"

    def test_falls_back_to_name_when_the_live_monitor_has_no_marker(self):
        seed = [{"key": "glances-bee", "name": "Glances Beelink"}]
        live = [{"id": 7, "name": "Glances Beelink", "description": "Beelink metrics agent."}]

        create, edit, delete = diff_monitors(seed, live)

        assert create == []
        assert delete == [], "the first sync must adopt existing monitors, not wipe them"
        assert [m["id"] for m in edit] == [7]

    def test_marker_wins_over_a_conflicting_name(self):
        # Two live monitors: one carries the key, another merely shares the name.
        seed = [{"key": "k1", "name": "Shared Name"}]
        live = [
            {"id": 1, "name": "Something Else", "description": embed_key("", "k1")},
            {"id": 2, "name": "Shared Name", "description": ""},
        ]

        _, edit, delete = diff_monitors(seed, live)

        assert [m["id"] for m in edit] == [1]
        assert [m["id"] for m in delete] == [2]

    def test_a_live_monitor_matching_nothing_is_deleted(self):
        # The seed is SSOT — that is what declarative sync means.
        seed = []
        live = [{"id": 9, "name": "Retired Service", "description": ""}]

        create, edit, delete = diff_monitors(seed, live)

        assert create == []
        assert edit == []
        assert [m["id"] for m in delete] == [9]

    def test_a_seed_entry_matching_nothing_is_created(self):
        seed = [{"key": "new-one", "name": "Brand New"}]

        create, edit, delete = diff_monitors(seed, [])

        assert [m["key"] for m in create] == ["new-one"]
        assert edit == []
        assert delete == []

    def test_one_live_monitor_is_never_claimed_by_two_seed_entries(self):
        # Both seed rows fall back to the same name; only one may adopt it.
        seed = [{"key": "a", "name": "Dup"}, {"key": "b", "name": "Dup"}]
        live = [{"id": 3, "name": "Dup", "description": ""}]

        create, edit, delete = diff_monitors(seed, live)

        assert len(edit) == 1
        assert len(create) == 1
        assert delete == []


class TestComparisonUsesOnlyFieldsTheSyncWrites:
    """Regression: comparing a field the apply path never writes is a dirty flag
    that no edit can clear, so the monitor is rewritten on every single run.

    The first version of this module stripped `active`, `tags` and
    `notificationIDList` from the live side but not from the seed side, so all 31
    real monitors reported dirty forever. The unit fixtures missed it because they
    carried none of those fields — which is why these use the real seed's shape.
    """

    REAL_SHAPE = {
        "name": "Infra · Node · VPS SSH",
        "type": "port",
        "hostname": "162.55.57.175",
        "port": 22,
        "interval": 120,
        "active": True,
        "tags": ["infra"],
        "notificationIDList": [1],
        "description": "Hetzner CAX21 VPS SSH port.",
    }

    def test_a_converged_monitor_with_the_real_seed_shape_is_a_no_op(self):
        seed = [{**self.REAL_SHAPE, "key": "vps-ssh"}]
        live = [
            {
                **self.REAL_SHAPE,
                "id": 1,
                "description": embed_key(self.REAL_SHAPE["description"], "vps-ssh"),
            }
        ]

        create, edit, delete = diff_monitors(seed, live)

        assert (create, edit, delete) == ([], [], [])

    def test_tags_alone_never_mark_a_monitor_dirty(self):
        # Tags are applied by a separate API call, not by the edit. Flagging them
        # would request an edit that cannot fix the difference.
        seed = [{**self.REAL_SHAPE, "key": "k", "tags": ["infra", "new"]}]
        live = [
            {
                **self.REAL_SHAPE,
                "id": 1,
                "description": embed_key(self.REAL_SHAPE["description"], "k"),
            }
        ]

        _, edit, _ = diff_monitors(seed, live)

        assert edit == []

    def test_a_field_the_sync_does_write_still_marks_it_dirty(self):
        # The guard above must not silence real drift.
        seed = [{**self.REAL_SHAPE, "key": "k", "interval": 300}]
        live = [
            {
                **self.REAL_SHAPE,
                "id": 1,
                "description": embed_key(self.REAL_SHAPE["description"], "k"),
            }
        ]

        _, edit, _ = diff_monitors(seed, live)

        assert [m["id"] for m in edit] == [1]


class TestDiffIsNonDestructiveOnASteadyState:
    """The regression that #962 is actually about."""

    def test_an_unchanged_seed_produces_no_deletes_and_no_creates(self):
        seed = [
            {"key": "k1", "name": "One", "interval": 60},
            {"key": "k2", "name": "Two", "interval": 120},
        ]
        live = [
            {"id": 1, "name": "One", "interval": 60, "description": embed_key("", "k1")},
            {"id": 2, "name": "Two", "interval": 120, "description": embed_key("", "k2")},
        ]

        create, edit, delete = diff_monitors(seed, live)

        assert create == []
        assert delete == []
        assert edit == [], "a converged instance must be a no-op, not 31 rewrites"

    def test_only_the_changed_monitor_is_edited(self):
        seed = [
            {"key": "k1", "name": "One", "interval": 60},
            {"key": "k2", "name": "Two", "interval": 300},
        ]
        live = [
            {"id": 1, "name": "One", "interval": 60, "description": embed_key("", "k1")},
            {"id": 2, "name": "Two", "interval": 120, "description": embed_key("", "k2")},
        ]

        _, edit, _ = diff_monitors(seed, live)

        assert [m["id"] for m in edit] == [2]

    def test_an_unkeyed_seed_against_an_unmarked_instance_is_a_no_op(self):
        # Today's seed has no `key` fields at all. Until the migration adds them,
        # a converged instance must still report clean — otherwise every run
        # rewrites all 31 monitors and the "no-op" acceptance criterion is met
        # only in the sense that nothing is deleted.
        seed = [{"name": "One", "interval": 60}]
        live = [{"id": 1, "name": "One", "interval": 60, "description": ""}]

        create, edit, delete = diff_monitors(seed, live)

        assert (create, edit, delete) == ([], [], [])

    def test_an_unmarked_but_otherwise_identical_monitor_is_edited_to_stamp_the_key(self):
        # Migration case: converged in every field except that it carries no marker.
        # It must still be edited once, or the key never lands and the next rename
        # falls back to name-matching forever.
        seed = [{"key": "k1", "name": "One", "interval": 60}]
        live = [{"id": 1, "name": "One", "interval": 60, "description": ""}]

        _, edit, delete = diff_monitors(seed, live)

        assert delete == []
        assert [m["id"] for m in edit] == [1]
