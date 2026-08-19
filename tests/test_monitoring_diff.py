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

import pytest

from toolkit.features.monitoring_diff import (
    PushTokenError,
    diff_monitors,
    embed_key,
    extract_key,
    hydrate_push_tokens,
    strip_key,
    wants_notifications,
)


def _diff(seed, live):
    """`diff_monitors` with notification comparison switched off.

    Every test in this file predates #912 and exercises unrelated behavior —
    passing `has_default_notification=False` skips the notification check
    entirely (see `_needs_edit`), reproducing the exact pre-#912 comparison so
    none of these fixtures need an unrelated `notificationIDList`.
    `TestNotificationMuting` below calls `diff_monitors` directly instead.
    """
    return diff_monitors(seed, live, muted_tags=frozenset(), has_default_notification=False)


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

        create, edit, delete = _diff(seed, live)

        assert create == []
        assert delete == []
        assert [m["id"] for m in edit] == [7], "a rename must edit, never delete+create"

    def test_falls_back_to_name_when_the_live_monitor_has_no_marker(self):
        seed = [{"key": "glances-bee", "name": "Glances Beelink"}]
        live = [{"id": 7, "name": "Glances Beelink", "description": "Beelink metrics agent."}]

        create, edit, delete = _diff(seed, live)

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

        _, edit, delete = _diff(seed, live)

        assert [m["id"] for m in edit] == [1]
        assert [m["id"] for m in delete] == [2]

    def test_a_live_monitor_matching_nothing_is_deleted(self):
        # The seed is SSOT — that is what declarative sync means.
        seed = []
        live = [{"id": 9, "name": "Retired Service", "description": ""}]

        create, edit, delete = _diff(seed, live)

        assert create == []
        assert edit == []
        assert [m["id"] for m in delete] == [9]

    def test_a_seed_entry_matching_nothing_is_created(self):
        seed = [{"key": "new-one", "name": "Brand New"}]

        create, edit, delete = _diff(seed, [])

        assert [m["key"] for m in create] == ["new-one"]
        assert edit == []
        assert delete == []

    def test_one_live_monitor_is_never_claimed_by_two_seed_entries(self):
        # Both seed rows fall back to the same name; only one may adopt it.
        seed = [{"key": "a", "name": "Dup"}, {"key": "b", "name": "Dup"}]
        live = [{"id": 3, "name": "Dup", "description": ""}]

        create, edit, delete = _diff(seed, live)

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

        create, edit, delete = _diff(seed, live)

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

        _, edit, _ = _diff(seed, live)

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

        _, edit, _ = _diff(seed, live)

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

        create, edit, delete = _diff(seed, live)

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

        _, edit, _ = _diff(seed, live)

        assert [m["id"] for m in edit] == [2]

    def test_an_unkeyed_seed_against_an_unmarked_instance_is_a_no_op(self):
        # Today's seed has no `key` fields at all. Until the migration adds them,
        # a converged instance must still report clean — otherwise every run
        # rewrites all 31 monitors and the "no-op" acceptance criterion is met
        # only in the sense that nothing is deleted.
        seed = [{"name": "One", "interval": 60}]
        live = [{"id": 1, "name": "One", "interval": 60, "description": ""}]

        create, edit, delete = _diff(seed, live)

        assert (create, edit, delete) == ([], [], [])

    def test_an_unmarked_but_otherwise_identical_monitor_is_edited_to_stamp_the_key(self):
        # Migration case: converged in every field except that it carries no marker.
        # It must still be edited once, or the key never lands and the next rename
        # falls back to name-matching forever.
        seed = [{"key": "k1", "name": "One", "interval": 60}]
        live = [{"id": 1, "name": "One", "interval": 60, "description": ""}]

        _, edit, delete = _diff(seed, live)

        assert delete == []
        assert [m["id"] for m in edit] == [1]


class TestWantsNotifications:
    """The tag-only half of the notification decision (#912)."""

    def test_an_entry_with_no_muted_tag_wants_notifications(self):
        assert wants_notifications({"tags": ["infra"]}, muted_tags=frozenset({"staging"})) is True

    def test_an_entry_carrying_a_muted_tag_does_not(self):
        assert wants_notifications({"tags": ["staging", "data"]}, muted_tags=frozenset({"staging"})) is False

    def test_an_entry_with_no_tags_at_all_wants_notifications(self):
        assert wants_notifications({}, muted_tags=frozenset({"staging"})) is True


class TestNotificationMuting:
    """Boolean-presence comparison against `muted_tags` (#912).

    Calls `diff_monitors` directly rather than through the `_diff` helper
    above — `has_default_notification=False` is exactly what that helper
    switches off, and these tests are about what happens when it is on.
    """

    MUTED = frozenset({"staging"})

    def test_a_muted_monitor_with_live_notifications_is_edited_to_clear_them(self):
        seed = [{"key": "k1", "name": "One", "tags": ["staging"]}]
        live = [{"id": 1, "name": "One", "description": embed_key("", "k1"), "notificationIDList": [1]}]

        _, edit, _ = diff_monitors(seed, live, muted_tags=self.MUTED, has_default_notification=True)

        assert [m["id"] for m in edit] == [1]

    def test_a_muted_monitor_already_without_notifications_is_a_no_op(self):
        seed = [{"key": "k1", "name": "One", "tags": ["staging"]}]
        live = [{"id": 1, "name": "One", "description": embed_key("", "k1"), "notificationIDList": []}]

        _, edit, _ = diff_monitors(seed, live, muted_tags=self.MUTED, has_default_notification=True)

        assert edit == []

    def test_an_unmuted_monitor_with_notifications_is_a_no_op(self):
        seed = [{"key": "k1", "name": "One", "tags": ["infra"]}]
        live = [{"id": 1, "name": "One", "description": embed_key("", "k1"), "notificationIDList": [1]}]

        _, edit, _ = diff_monitors(seed, live, muted_tags=self.MUTED, has_default_notification=True)

        assert edit == []

    def test_an_unmuted_monitor_missing_notifications_is_edited_to_attach_them(self):
        seed = [{"key": "k1", "name": "One", "tags": ["infra"]}]
        live = [{"id": 1, "name": "One", "description": embed_key("", "k1")}]

        _, edit, _ = diff_monitors(seed, live, muted_tags=self.MUTED, has_default_notification=True)

        assert [m["id"] for m in edit] == [1]

    def test_the_write_shaped_dict_reads_identically_to_the_list_shape(self):
        # `_params()` sends `{"1": True}`; live reads return `[1]`. A monitor
        # already converged under one shape must not look dirty under the other.
        seed = [{"key": "k1", "name": "One", "tags": ["infra"]}]
        live = [
            {
                "id": 1,
                "name": "One",
                "description": embed_key("", "k1"),
                "notificationIDList": {"1": True},
            }
        ]

        _, edit, _ = diff_monitors(seed, live, muted_tags=self.MUTED, has_default_notification=True)

        assert edit == []

    def test_with_no_default_notification_the_check_is_skipped_not_converged_to_zero(self):
        # A from-scratch instance (OBS-014) has nothing to attach. Comparing
        # anyway would flag every notified monitor dirty and, on apply, wipe
        # whatever links it actually has — fail-safe is skipping, not zeroing.
        seed = [{"key": "k1", "name": "One", "tags": ["infra"]}]
        live = [{"id": 1, "name": "One", "description": embed_key("", "k1"), "notificationIDList": [1]}]

        _, edit, _ = diff_monitors(seed, live, muted_tags=self.MUTED, has_default_notification=False)

        assert edit == []

    def test_the_real_staging_tagged_shape_needs_exactly_one_edit_to_mute(self):
        # The actual case #912 is about: a staging monitor in today's seed
        # shape, live with the notification it currently carries.
        seed = [
            {
                "key": "staging-web-grafana-staging",
                "name": "Staging · Web · Grafana Staging",
                "type": "http",
                "url": "https://grafana.staging.kubelab.live",
                "tags": ["staging", "data"],
            }
        ]
        live = [
            {
                "id": 42,
                "name": "Staging · Web · Grafana Staging",
                "type": "http",
                "url": "https://grafana.staging.kubelab.live",
                "tags": ["staging", "data"],
                "notificationIDList": [1],
                "description": embed_key("", "staging-web-grafana-staging"),
            }
        ]

        _, edit, _ = diff_monitors(seed, live, muted_tags=self.MUTED, has_default_notification=True)

        assert [m["id"] for m in edit] == [42]


class TestPushTokenHydration:
    """The token lives in SOPS and is married to the seed in memory (TOOL-038).

    `monitors.json` is committed to a public repository and the push endpoint is
    publicly routed, so a token in the seed is a live credential whose only power
    is to post "still alive" at the monitor that exists to notice silence. These
    tests pin both directions of the invariant: the value arrives from the secret
    store, and it is refused if it ever arrives from the file.
    """

    def test_a_push_monitor_receives_its_token_from_the_secret_store(self):
        seed = [{"key": "ops-heartbeat", "name": "Backup heartbeat", "type": "push"}]
        [entry] = hydrate_push_tokens(seed, {"ops-heartbeat": "s3cr3t"})
        assert entry["pushToken"] == "s3cr3t"

    def test_non_push_monitors_pass_through_untouched(self):
        seed = [{"key": "vps-ssh", "name": "VPS SSH", "type": "port", "port": 22}]
        assert hydrate_push_tokens(seed, {}) == seed

    def test_it_does_not_mutate_the_seed_it_was_given(self):
        """The caller re-reads the seed for the diff; a mutated input would leak
        the token back into anything that later writes the file."""
        seed = [{"key": "ops-heartbeat", "name": "Backup heartbeat", "type": "push"}]
        hydrate_push_tokens(seed, {"ops-heartbeat": "s3cr3t"})
        assert "pushToken" not in seed[0]

    def test_a_missing_token_refuses_rather_than_letting_kuma_mint_one(self):
        """The silent fallback is worse than the error: `uptime_kuma_api` invents
        a token for a tokenless push monitor, which yields a monitor at an
        address no sender knows — a watchdog that alerts forever."""
        seed = [{"key": "ops-heartbeat", "name": "Backup heartbeat", "type": "push"}]
        with pytest.raises(PushTokenError) as exc:
            hydrate_push_tokens(seed, {})
        assert "ops-heartbeat" in str(exc.value)

    def test_the_refusal_names_the_command_that_fixes_it(self):
        seed = [{"key": "ops-heartbeat", "name": "Backup heartbeat", "type": "push"}]
        with pytest.raises(PushTokenError) as exc:
            hydrate_push_tokens(seed, {})
        assert "toolkit secrets set" in str(exc.value)
        assert "push_tokens" in str(exc.value)

    def test_an_empty_string_token_counts_as_missing(self):
        """A blank SOPS value would otherwise hydrate a monitor with no token
        and pass every later check."""
        seed = [{"key": "ops-heartbeat", "name": "Backup heartbeat", "type": "push"}]
        with pytest.raises(PushTokenError):
            hydrate_push_tokens(seed, {"ops-heartbeat": ""})

    def test_a_push_monitor_with_no_key_is_refused(self):
        """Identity is how the token is looked up, so a keyless push entry has no
        resolvable token — and adopting one by name would bind a credential to a
        mutable field."""
        seed = [{"name": "Backup heartbeat", "type": "push"}]
        with pytest.raises(PushTokenError):
            hydrate_push_tokens(seed, {"ops-heartbeat": "s3cr3t"})

    def test_an_inline_token_in_the_seed_is_refused(self):
        """The leak this design exists to prevent. It can only arrive by someone
        hand-editing the file, so it is named rather than quietly honoured."""
        seed = [
            {
                "key": "ops-heartbeat",
                "name": "Backup heartbeat",
                "type": "push",
                "pushToken": "leaked-into-git",
            }
        ]
        with pytest.raises(PushTokenError) as exc:
            hydrate_push_tokens(seed, {"ops-heartbeat": "s3cr3t"})
        assert "inline" in str(exc.value)

    def test_every_offender_is_named_at_once(self):
        """A sync refusing one monitor per run makes fixing three of them three
        edit-and-rerun cycles."""
        seed = [
            {"key": "a", "name": "A", "type": "push"},
            {"key": "b", "name": "B", "type": "push"},
        ]
        with pytest.raises(PushTokenError) as exc:
            hydrate_push_tokens(seed, {})
        assert "'a'" in str(exc.value) and "'b'" in str(exc.value)


class TestPushTokenDrift:
    """A token rotated outside the pipeline must read as drift, not as converged.

    This is why `pushToken` is in `WRITABLE_FIELDS`. Without it a monitor whose
    live token no longer matches the sender's reports UP forever while receiving
    nothing — the failure mode a dead-man's-switch cannot afford.
    """

    def test_a_rotated_live_token_is_flagged_for_edit(self):
        seed = hydrate_push_tokens(
            [{"key": "ops-heartbeat", "name": "Backup heartbeat", "type": "push"}],
            {"ops-heartbeat": "the-real-one"},
        )
        live = [
            {
                "id": 7,
                "name": "Backup heartbeat",
                "type": "push",
                "pushToken": "rotated-in-the-ui",
                "description": embed_key("", "ops-heartbeat"),
            }
        ]
        _, to_edit, _ = _diff(seed, live)
        assert [m["id"] for m in to_edit] == [7]

    def test_a_matching_token_is_a_no_op(self):
        seed = hydrate_push_tokens(
            [{"key": "ops-heartbeat", "name": "Backup heartbeat", "type": "push"}],
            {"ops-heartbeat": "the-real-one"},
        )
        live = [
            {
                "id": 7,
                "name": "Backup heartbeat",
                "type": "push",
                "pushToken": "the-real-one",
                "description": embed_key("", "ops-heartbeat"),
            }
        ]
        to_create, to_edit, to_delete = _diff(seed, live)
        assert (to_create, to_edit, to_delete) == ([], [], [])
