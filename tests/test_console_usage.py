"""#3341: the A8 gate is read from `console_usage`, never from memory.

ADR-066 A8 hands over to the Vikunja retirement (#2587) once the console was opened on
at least 5 of 14 consecutive UTC days. The counter (#3334) stores one row per identity
and day; this reads it back through a read-only transaction and does the window
arithmetic here, where it can be tested without a database.
"""

from __future__ import annotations

from datetime import date, timedelta

from toolkit.features import console_usage as cu


def _days(*offsets: int) -> list[date]:
    start = date(2026, 11, 13)
    return [start + timedelta(days=o) for o in offsets]


class TestWindow:
    def test_five_days_inside_fourteen_hold_the_gate(self) -> None:
        w = cu.best_window(_days(0, 2, 5, 9, 13))
        assert (w.start, w.days_used) == (date(2026, 11, 13), 5)
        assert w.holds

    def test_five_days_spread_over_fifteen_do_not(self) -> None:
        w = cu.best_window(_days(0, 2, 5, 9, 14))
        assert w.days_used == 4
        assert not w.holds

    def test_the_best_window_wins_over_the_first(self) -> None:
        w = cu.best_window(_days(0, 20, 21, 22, 23, 24))
        assert (w.start, w.days_used) == (date(2026, 12, 3), 5)

    def test_history_shorter_than_the_window_still_counts(self) -> None:
        assert cu.best_window(_days(0, 1, 2, 3, 4)).holds

    def test_no_history_reads_zero(self) -> None:
        w = cu.best_window([])
        assert (w.start, w.days_used, w.holds) == (None, 0, False)


class TestParse:
    def test_rows_group_by_identity(self) -> None:
        rows = cu.parse_rows("operator|2026-11-13\noperator|2026-11-14\nother|2026-11-13\n")
        assert rows == {"operator": _days(0, 1), "other": _days(0)}

    def test_a_malformed_line_is_refused_not_skipped(self) -> None:
        try:
            cu.parse_rows("operator|not-a-date\n")
        except ValueError:
            return
        raise AssertionError("a row that is not identity|date must fail the read")


class TestRead:
    def test_the_query_runs_in_a_read_only_transaction(self) -> None:
        sql = cu.QUERY.upper()
        assert sql.lstrip().startswith("BEGIN READ ONLY")
        assert "INSERT" not in sql and "UPDATE" not in sql and "DELETE" not in sql

    def test_report_reads_through_the_postgres_container_and_names_the_gate(self) -> None:
        seen: list[list[str]] = []

        def run(argv: list[str], stdin: str | None = None) -> tuple[int, str, str]:
            seen.append(argv)
            assert stdin == cu.QUERY
            return 0, "BEGIN\noperator|2026-11-13\noperator|2026-11-14\nCOMMIT\n", ""

        lines = cu.report("prod", run=run, kubeconfig="/k", database="api")
        assert seen and seen[0][:3] == ["kubectl", "--kubeconfig", "/k"]
        assert "deploy/postgres" in seen[0] and seen[0][-1] == "api"
        assert any("operator" in line and "2 of 14" in line and "not yet" in line for line in lines)

    def test_a_failed_read_raises_instead_of_reporting_zero(self) -> None:
        def run(argv: list[str], stdin: str | None = None) -> tuple[int, str, str]:
            return 1, "", 'relation "console_usage" does not exist'

        try:
            cu.report("prod", run=run, kubeconfig="/k", database="api")
        except cu.ReadError as exc:
            assert "console_usage" in str(exc)
            return
        raise AssertionError("a failed read must not read as no usage")
