"""Derive the lesson index's counters from the files, instead of writing them.

The index states how many lessons exist, in three places: a total at the top of
`docs/lessons/_index.md`, a per-category column in its table, and a heading in
each category's own `_index.md`. `tests/test_lesson_index_integrity.py` asserts
all three against the files on disk, and that guard is correct -- it is what
stops the index drifting from the corpus.

The problem is not the guard, it is that the numbers are **shared mutable
counters** that every lesson PR must write (#1649). They are correct when a
branch is authored and wrong the moment another lesson PR merges first, and git
merges the line as text without raising a conflict. Four collisions in two days,
across three parallel sessions; on one of them the merge produced a
self-consistent *lie* -- a counter that balanced while the row indexing a real
lesson had been dropped.

So the numbers stop being written by hand. This module recomputes them from the
files, and a pre-commit hook applies it, which is the difference between a rule
people must remember at merge time and a fact that cannot be wrong when it
leaves the machine. "Derived once is not derived", as #1649 puts it: deriving
the count while authoring is exactly what failed.

Deliberately NOT removing the numbers instead. The guard would go vacuous, and
this corpus has spent the week writing down why a check that cannot fail is
worse than no check.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from collections.abc import Callable

#: `433 lessons, one file each. Newest: 2026-09-05. ...`
TOTAL_LINE = re.compile(r"^(?P<n>\d+) lessons, one file each\. Newest: (?P<date>\d{4}-\d{2}-\d{2})\.")

#: `| [observability](observability/_index.md) | 17 | Metrics, logs, alerting |`
CATEGORY_ROW = re.compile(r"^\| \[(?P<slug>[a-z-]+)\]\((?P=slug)/_index\.md\) \| (?P<n>\d+) \|")

#: `17 lessons, newest first. Back to [all categories](../_index.md).`
CATEGORY_LINE = re.compile(r"^(?P<n>\d+) lessons, newest first\.")

#: `| 429 | [title](lesson-429-....md) | 2026-09-04 |`
LESSON_ROW = re.compile(r"^\| \d+ \| \[.*\]\((?P<file>lesson-[^)]+\.md)\) \| (?P<date>\d{4}-\d{2}-\d{2}) \|")


@dataclasses.dataclass(frozen=True)
class Fix:
    """One counter that disagreed with the files."""

    path: pathlib.Path
    line_number: int
    was: str
    now: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line_number}  {self.was.strip()!r} -> {self.now.strip()!r}"


def category_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(d for d in root.iterdir() if d.is_dir() and (d / "_index.md").exists())


def lesson_files(category: pathlib.Path) -> list[pathlib.Path]:
    return sorted(category.glob("lesson-*.md"))


def newest_date(root: pathlib.Path) -> str | None:
    """The most recent date appearing in any category index's rows.

    Read from the ROWS rather than from file mtimes: mtime records when a file
    was last touched, which a rebase or a typo fix changes, and the index is
    stating when the newest lesson was written.
    """
    dates = [
        m.group("date")
        for cat in category_dirs(root)
        for line in (cat / "_index.md").read_text(encoding="utf-8").splitlines()
        if (m := LESSON_ROW.match(line))
    ]
    return max(dates) if dates else None


def _rewrite(path: pathlib.Path, apply: bool, edit: Callable[[str], str | None]) -> list[Fix]:
    """Run `edit` over a file's lines, collecting (and optionally writing) fixes."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    fixes: list[Fix] = []
    for i, line in enumerate(lines):
        replacement = edit(line)
        if replacement is not None and replacement != line:
            fixes.append(Fix(path=path, line_number=i + 1, was=line, now=replacement))
            lines[i] = replacement
    if fixes and apply:
        path.write_text("".join(lines), encoding="utf-8")
    return fixes


def reconcile(root: pathlib.Path, apply: bool = False) -> list[Fix]:
    """Bring every counter in the lesson indexes in line with the files.

    Returns the fixes needed; writes them when `apply`. An empty list means the
    indexes already agree with the corpus.
    """
    counts = {cat.name: len(lesson_files(cat)) for cat in category_dirs(root)}
    total = sum(counts.values())
    newest = newest_date(root)

    fixes: list[Fix] = []

    def top_level(line: str) -> str | None:
        if m := TOTAL_LINE.match(line):
            date = newest or m.group("date")
            return f"{total} lessons, one file each. Newest: {date}. Open a category for its list.\n"
        if m := CATEGORY_ROW.match(line):
            slug = m.group("slug")
            if slug in counts:
                return re.sub(r"\| \d+ \|", f"| {counts[slug]} |", line, count=1)
        return None

    fixes += _rewrite(root / "_index.md", apply, top_level)

    def category_heading(n: int) -> Callable[[str], str | None]:
        def edit(line: str) -> str | None:
            if CATEGORY_LINE.match(line):
                return CATEGORY_LINE.sub(f"{n} lessons, newest first.", line, count=1)
            return None

        return edit

    for cat in category_dirs(root):
        fixes += _rewrite(cat / "_index.md", apply, category_heading(counts[cat.name]))

    return fixes
