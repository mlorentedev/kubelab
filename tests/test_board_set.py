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
    guard_closed,
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


class TestClosedIssueGuard:
    """TOOL-053 (#1504): a re-run must not put a closed issue back In Progress.

    Observed 2026-08-31 on #1494. The workflow's only guard was
    `if: github.event.issue.state == 'open'`, read from the **event payload**.
    Re-running the job replays the payload as it was when the event fired, so
    after the issue closed at 01:50:16Z, the re-run at 02:28 believed it was
    open and wrote `In Progress` onto a finished ticket. The board then claimed
    work that had ended 38 minutes earlier — the inverse of the standing order
    the automation exists to serve.

    Same class as BUG-066 in dotfiles' spec-gate ("a re-run replays the original
    payload, so a payload-sourced gate judged the PR as it was before the
    operator fixed it"). The remedy is the same and is not a guard clause on the
    payload: read the state live, and decide here, where a test can execute it.
    """

    @staticmethod
    def _item(*, issue_state: str, closed_at: str | None = None, values: dict[str, str] | None = None) -> ItemState:
        return ItemState(item_id="I1", number=1494, values=values or {}, issue_state=issue_state, closed_at=closed_at)

    def test_an_open_issue_moves_ahead(self) -> None:
        guard = guard_closed(self._item(issue_state="OPEN"), {"Status": "In Progress"}, on_closed="fail")
        assert guard.action == "proceed"

    def test_a_closed_issue_refuses_In_Progress_and_names_when_it_closed(self) -> None:
        """The human path: silence is the failure, so the message carries the date."""
        guard = guard_closed(
            self._item(issue_state="CLOSED", closed_at="2026-09-01T01:50:16Z"),
            {"Status": "In Progress"},
            on_closed="fail",
        )
        assert guard.action == "refuse"
        assert "2026-09-01T01:50:16Z" in guard.message

    def test_a_closed_issue_skips_for_automation_and_says_why(self) -> None:
        """The workflow path: a re-run whose subject has closed is a no-op, not a red job.

        The distinction from `refuse` is the whole option. Automation must be able
        to report "nothing to do, and here is the reason" without turning a board
        hygiene re-run into an incident; a human must not get that silence by
        accident, because for them the request itself is the mistake.
        """
        guard = guard_closed(
            self._item(issue_state="CLOSED", closed_at="2026-09-01T01:50:16Z"),
            {"Status": "In Progress"},
            on_closed="skip",
        )
        assert guard.action == "skip"
        assert "In Progress" in guard.message and "1494" in guard.message

    def test_only_the_move_to_In_Progress_is_guarded(self) -> None:
        """Setting Priority, or correcting Status to Done, on a closed issue is legitimate.

        A guard that refused every write would make the board unrepairable after
        closure — and #1494's own correction (In Progress -> Done) is exactly the
        write this would have blocked.
        """
        closed = self._item(issue_state="CLOSED", closed_at="2026-09-01T01:50:16Z")
        assert guard_closed(closed, {"Priority": "P2"}, on_closed="fail").action == "proceed"
        assert guard_closed(closed, {"Status": "Done"}, on_closed="fail").action == "proceed"

    def test_a_write_already_holding_In_Progress_is_still_guarded(self) -> None:
        """Idempotence does not save a rerun: the desired value is what it is.

        `plan()` returns nothing when Status already reads In Progress, so if the
        guard were derived from planned changes alone, re-running against an issue
        that was moved In Progress *while open* and closed afterwards would
        proceed silently and report success. The guard reads the request.
        """
        state = self._item(issue_state="CLOSED", closed_at="2026-09-01T01:50:16Z", values={"Status": "In Progress"})
        assert plan(state, {"Status": "In Progress"}) == ()
        assert guard_closed(state, {"Status": "In Progress"}, on_closed="fail").action == "refuse"

    def test_an_unrecognised_on_closed_value_fails_rather_than_defaulting_open(self) -> None:
        """`--closedmaybe` must not fall through to the permissive branch."""
        with pytest.raises(ValueError):
            guard_closed(self._item(issue_state="CLOSED"), {"Status": "In Progress"}, on_closed="maybe")

    def test_a_state_the_api_has_never_returned_is_not_treated_as_open(self) -> None:
        """Fail closed on an unknown value: the guard's cost of being wrong is a stale board."""
        guard = guard_closed(self._item(issue_state="ARCHIVED"), {"Status": "In Progress"}, on_closed="fail")
        assert guard.action == "refuse"
