"""DEBT-012 (#1469): a lesson with no index row is a lesson nobody will find.

`docs/lessons/_format.md` ends with an instruction — *"After adding a file, add
its row to the category's `_index.md` and bump the count"* — and nothing checked
that it happened. Two ways it silently does not:

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
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LESSONS = REPO_ROOT / "docs" / "lessons"

#: `NN lessons, ...` on the category index's summary line, and the same shape at
#: the top level. Matched rather than parsed as Markdown: the count is prose, and
#: prose is what drifts.
_COUNT = re.compile(r"^(\d+) lessons\b", re.M)

#: A table row's link target: `| 402 | [title](lesson-402-....md) | date |`
_ROW_TARGET = re.compile(r"\]\((lesson-[^)]+\.md)\)")


def _categories() -> list[pathlib.Path]:
    return sorted(p for p in LESSONS.iterdir() if p.is_dir() and (p / "_index.md").exists())


def _lesson_files(category: pathlib.Path) -> set[str]:
    return {p.name for p in category.glob("lesson-*.md")}


def _rows(category: pathlib.Path) -> list[str]:
    return _ROW_TARGET.findall((category / "_index.md").read_text())


def _stated_count(index: pathlib.Path) -> int:
    match = _COUNT.search(index.read_text())
    assert match, f"{index.relative_to(REPO_ROOT)} has no 'N lessons' summary line"
    return int(match.group(1))


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

    def test_the_stated_count_matches_the_files(self, category: pathlib.Path) -> None:
        stated = _stated_count(category / "_index.md")
        actual = len(_lesson_files(category))
        assert stated == actual, f"{category.name}/_index.md says {stated} lessons, {actual} files exist"


class TestTopLevelIndex:
    def test_the_total_matches_every_file(self) -> None:
        stated = _stated_count(LESSONS / "_index.md")
        actual = sum(len(_lesson_files(c)) for c in _categories())
        assert stated == actual, f"docs/lessons/_index.md says {stated} lessons, {actual} files exist"

    def test_each_categorys_number_matches_its_own_index(self) -> None:
        """The top level restates every category's count; both copies must agree."""
        text = (LESSONS / "_index.md").read_text()
        for category in _categories():
            row = re.search(rf"\|\s*\[{re.escape(category.name)}\]\([^)]+\)\s*\|\s*(\d+)\s*\|", text)
            assert row, f"docs/lessons/_index.md has no row for category {category.name}"
            assert int(row.group(1)) == len(_lesson_files(category)), (
                f"top-level index says {row.group(1)} for {category.name}, "
                f"{len(_lesson_files(category))} files exist"
            )

    def test_every_category_directory_appears(self) -> None:
        """A whole category missing from the top level hides all of its lessons at once."""
        text = (LESSONS / "_index.md").read_text()
        for category in _categories():
            assert f"({category.name}/_index.md)" in text, f"category {category.name} is not linked from the top level"
