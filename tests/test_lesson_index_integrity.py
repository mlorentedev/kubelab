"""DEBT-012 (#1469): a lesson with no index row is a lesson nobody will find.

`docs/lessons/_format.md` ends with an instruction — *"After adding a file, add
its row to the category's `_index.md`"* — and nothing checked that it happened. Two ways it silently does not:

1. **A clean merge drops a row.** Recorded in lesson-401: two branches both
   top-inserted into the same `_index.md` table, git merged them with no
   conflict, and one row was gone. The result is still valid Markdown holding a
   plausible table, so no lint and no review comment catches it.
2. **The instruction is skipped**, which is what an instruction with no
   mechanism eventually does (lesson-365).

The files are the data and the indexes are the only navigation, so a dropped row
is a silent deletion from a reader's point of view while the content sits on
disk untouched.

**Why a test and not a generator.** Generating the indexes from the files would
also close this, and is rejected deliberately: the category indexes carry a
curated order and titles that are sometimes shortened relative to the lesson's
own heading. A generator flattens both. This keeps the file hand-written and
only refuses to let it drift.

**Why the indexes state no count (#2525).** They used to: a total, a column per
category and a heading per category. Each was a shared mutable line that every
lesson PR rewrote. Two PRs that each added a lesson merged their edits as text
with no conflict, and master broke twice on 2026-10-18. The three row tests
below already pin the count (every file has a row, every row has a file, no row
twice), so a stated number checked nothing they do not. `TestNoCommittedCount`
keeps one from coming back.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from toolkit.features.lessons_index import unmerged_indexes

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LESSONS = REPO_ROOT / "docs" / "lessons"

#: `NN lessons, ...`: the summary-line shape the indexes used before #2525.
_COUNT = re.compile(r"^(\d+) lessons\b", re.M)

#: `| [slug](slug/_index.md) | 56 | Scope |`: the top-level count column before #2525.
_CATEGORY_COUNT = re.compile(r"^\|\s*\[[a-z-]+\]\([a-z-]+/_index\.md\)\s*\|\s*\d+\s*\|", re.M)

#: A table row's link target: `| 402 | [title](lesson-402-....md) | date |`
_ROW_TARGET = re.compile(r"\]\((lesson-[^)]+\.md)\)")


def _categories() -> list[pathlib.Path]:
    return sorted(p for p in LESSONS.iterdir() if p.is_dir() and (p / "_index.md").exists())


def _lesson_files(category: pathlib.Path) -> set[str]:
    return {p.name for p in category.glob("lesson-*.md")}


def _rows(category: pathlib.Path) -> list[str]:
    return _ROW_TARGET.findall((category / "_index.md").read_text(encoding="utf-8"))


def test_there_are_categories_to_check() -> None:
    """Guards the guard: an empty discovery makes every test below vacuously green."""
    assert len(_categories()) >= 10


@pytest.mark.parametrize("category", _categories(), ids=lambda p: p.name)
class TestOneCategory:
    def test_every_lesson_file_has_a_row(self, category: pathlib.Path) -> None:
        """Matched by filename, never by title — titles get edited, links do not."""
        missing = _lesson_files(category) - set(_rows(category))
        assert not missing, (
            f"{category.name}/_index.md has no row for: {', '.join(sorted(missing))}. "
            "A lesson with no row is unreachable from the indexes."
        )

    def test_every_row_points_at_a_file_that_exists(self, category: pathlib.Path) -> None:
        """Catches the other direction: a rename that moved the file, leaving the row."""
        dangling = set(_rows(category)) - _lesson_files(category)
        assert not dangling, f"{category.name}/_index.md links to missing file(s): {', '.join(sorted(dangling))}"

    def test_no_row_is_duplicated(self, category: pathlib.Path) -> None:
        """Two rows for one lesson is the same merge accident, landing the other way."""
        rows = _rows(category)
        dupes = {name for name in rows if rows.count(name) > 1}
        assert not dupes, f"{category.name}/_index.md lists twice: {', '.join(sorted(dupes))}"


class TestNoCommittedCount:
    """A count written into an index is the shared line that broke master (#2525)."""

    @pytest.mark.parametrize(
        "index",
        [LESSONS / "_index.md", *(c / "_index.md" for c in _categories())],
        ids=lambda p: p.parent.name,
    )
    def test_no_index_states_a_lesson_count(self, index: pathlib.Path) -> None:
        stated = _COUNT.findall(index.read_text(encoding="utf-8"))
        assert not stated, (
            f"{index.relative_to(REPO_ROOT)} states a lesson count ({stated[0]}). Two PRs that each add "
            "a lesson rewrite that line from different bases and merge with no conflict (#2525). "
            "The row tests already pin the count, so drop the number."
        )

    def test_the_top_level_table_has_no_count_column(self) -> None:
        rows = _CATEGORY_COUNT.findall((LESSONS / "_index.md").read_text(encoding="utf-8"))
        assert not rows, f"docs/lessons/_index.md has a per-category count again: {rows[0]!r} (#2525)"

    def test_the_guard_matches_the_shapes_it_replaced(self) -> None:
        """Guards the guard: both patterns still recognise the lines they were written for."""
        assert _COUNT.findall("598 lessons, one file each. Newest: 2026-10-18.\n")
        assert _COUNT.findall("56 lessons, newest first. Back to [all categories](../_index.md).\n")
        assert _CATEGORY_COUNT.findall("| [kubernetes](kubernetes/_index.md) | 56 | Cluster |\n")


class TestNoUnfinishedMerge:
    """#1700: markers sit between well-formed rows, so every row test above passes over them."""

    def test_no_index_holds_conflict_markers(self) -> None:
        unmerged = unmerged_indexes(LESSONS)
        assert not unmerged, (
            f"conflict markers in docs/lessons/: {unmerged} (file: line numbers). The merge is not "
            "finished; resolve each conflict, then run `toolkit tools lessons-index --fix`."
        )


class TestTopLevelIndex:
    def test_every_category_directory_appears(self) -> None:
        """A whole category missing from the top level hides all of its lessons at once."""
        text = (LESSONS / "_index.md").read_text(encoding="utf-8")
        for category in _categories():
            assert f"({category.name}/_index.md)" in text, f"category {category.name} is not linked from the top level"
