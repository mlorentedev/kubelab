"""TOOL-046 (#1468): setting one issue's board fields, by name and idempotently.

Every test here is pure — no network, no `gh`. What is under test is the part
that was previously done by hand: resolving a human-readable option name to the
id a mutation needs, and deciding whether a mutation is needed at all.

The thing being replaced was a raw GraphQL call with pasted node ids. Its two
failure modes are what these tests pin: a stale pasted id writes a wrong value
with no error, and a re-run writes again because nothing compared first.
"""

from __future__ import annotations

import pytest

from toolkit.features.board_set import (
    Change,
    FieldInfo,
    ItemState,
    UnknownOptionError,
    plan,
    resolve_option,
)

PRIORITY = FieldInfo(field_id="F_pri", options={"P0": "o0", "P1": "o1", "P2": "o2", "P3": "o3"})
STREAM = FieldInfo(field_id="F_str", options={"Security & Identity": "os", "Toolkit & CLI": "ot"})


class TestPlanIsWhereIdempotenceLives:
    def test_a_field_already_at_its_desired_value_produces_no_change(self) -> None:
        """The stronger property: no mutation is *sent*, not a mutation that no-ops.

        A write that happens to change nothing still costs a request, can fail
        partway through a batch, and reads as an action in any audit log.
        """
        state = ItemState(item_id="I1", number=1468, values={"Priority": "P2", "Stream": "Toolkit & CLI"})
        assert plan(state, {"Priority": "P2", "Stream": "Toolkit & CLI"}) == ()

    def test_only_the_differing_fields_are_planned(self) -> None:
        state = ItemState(item_id="I1", number=1468, values={"Priority": "P2", "Stream": "Toolkit & CLI"})
        changes = plan(state, {"Priority": "P1", "Stream": "Toolkit & CLI"})
        assert changes == (Change(field="Priority", before="P2", after="P1"),)

    def test_an_unset_field_is_planned_and_reports_its_absence(self) -> None:
        """A freshly filed issue has no values at all — the common case."""
        state = ItemState(item_id="I1", number=1468, values={})
        (change,) = plan(state, {"Priority": "P2"})
        assert change.before is None
        assert "(unset)" in str(change), "the operator should see it was unset, not that it was 'None'"

    def test_a_field_absent_from_desired_is_never_touched(self) -> None:
        """Setting Priority must not clear Status. Partial updates are the norm here."""
        state = ItemState(item_id="I1", number=1468, values={"Status": "In Progress", "Priority": "P3"})
        changes = plan(state, {"Priority": "P1"})
        assert [c.field for c in changes] == ["Priority"]


class TestOptionResolution:
    def test_a_name_resolves_to_its_id(self) -> None:
        assert resolve_option("Priority", PRIORITY, "P1") == "o1"

    def test_an_option_with_spaces_and_punctuation_resolves(self) -> None:
        """The Stream names are the reason this exists — nobody pastes `755c78c1` correctly twice."""
        assert resolve_option("Stream", STREAM, "Security & Identity") == "os"

    def test_an_unknown_option_raises_and_lists_the_valid_ones(self) -> None:
        """Failing loudly is the whole point.

        The alternative to a lookup is a pasted id, and a pasted id that has
        gone stale writes a wrong value with no error at all. An exception
        naming the valid options is strictly better than a successful mutation
        nobody reads back.
        """
        with pytest.raises(UnknownOptionError) as exc:
            resolve_option("Priority", PRIORITY, "P9")
        message = str(exc.value)
        assert "P9" in message
        assert "P0, P1, P2, P3" in message, "the caller must be able to fix it from the error alone"

    def test_resolution_is_case_and_whitespace_exact(self) -> None:
        """Deliberately strict: a fuzzy match would pick a neighbour silently."""
        with pytest.raises(UnknownOptionError):
            resolve_option("Priority", PRIORITY, "p1")
