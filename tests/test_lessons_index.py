"""The lessons corpus is consistent: unique numbers, matching ids, indexed rows.

The indexes state no lesson count since #2525. The guard against one coming
back is `tests/test_lesson_index_integrity.py::TestNoCommittedCount`.

`docs/lessons/_format.md` states the contract — one file per lesson, the `id`
equal to the filename, numbers assigned in filing order and never reused, and a
row in the category index. None of it was enforced, and two of the three have
already drifted in practice.

The number collision is the one worth naming, because it is structural rather
than careless: two sessions each take "the next free number" from the same
master, and neither branch contains the other's file. Nothing is wrong on either
PR. The duplicate exists only in the merge, where no test was looking — and a
lesson number is a citation, so a duplicate silently makes two documents answer
to one reference.

Measured 2026-08-21: `lesson-362` landed twice, 26 minutes apart, from #1213 and
#1216. That is the second such collision in the repository's history; the first
(`lesson-360`, #1199) was caught by a `git fetch` mid-session rather than by any
control.

This catches it on the first PR opened after both have merged, which is the
earliest a single tree contains both.
"""

from __future__ import annotations

import pathlib
import re

from toolkit.features.lessons_index import LESSON_NAME, number_collisions

REPO = pathlib.Path(__file__).resolve().parent.parent
LESSONS = REPO / "docs/lessons"


def _lesson_files() -> list[pathlib.Path]:
    return sorted(LESSONS.glob("*/lesson-*.md"))


def test_the_scan_finds_the_corpus() -> None:
    """Without this, a moved directory turns every assertion below into a pass."""
    files = _lesson_files()
    assert len(files) > 300, (
        f"only {len(files)} lesson files found under {LESSONS}; the scan has drifted "
        f"and the checks below are asserting nothing"
    )


def test_every_lesson_filename_parses() -> None:
    """The predicate below skips a name it cannot parse, so nothing may be unparseable.

    `number_collisions` matches `LESSON_NAME` and moves on when a name does not
    fit, which is right for a function answering only about collisions — and it
    means a malformed filename would be excluded from the collision scan rather
    than reported by it. This is the anti-vacuity check for that skip: it asserts
    the set the predicate actually examines is the whole corpus.
    """
    unparseable = [f"{p.parent.name}/{p.name}" for p in _lesson_files() if not LESSON_NAME.match(p.name)]
    assert not unparseable, "these files are in the corpus but not scanned for collisions:\n  " + "\n  ".join(
        unparseable
    )


def test_no_two_lessons_share_a_number() -> None:
    """A lesson number is a citation. Two documents cannot answer to one.

    The predicate is IMPORTED from `toolkit.features.lessons_index`, not copied:
    the local pre-commit/pre-push gate refuses on the same function (#1678 AC5),
    and two implementations of one rule is how the local gate and CI come to
    disagree about what a collision is. One of them would then be wrong, silently,
    and the copy is always the one nobody updates.
    """
    collisions = number_collisions(LESSONS)
    assert not collisions, (
        "two lessons claim the same number:\n"
        + "\n".join(f"  {n}: {sorted(paths)}" for n, paths in sorted(collisions.items()))
        + "\n\nThis happens when two branches each take `the next free number` from the "
        "same master. Neither PR is wrong on its own; the duplicate exists only in the "
        "merge. Resolve it the way the format file prescribes — the one that landed "
        "FIRST keeps the number, the later one moves to the next free one, and both "
        "indexes follow. Check unmerged branches before picking, or this repeats."
    )


def test_every_lesson_id_matches_its_filename() -> None:
    """The format file's rule, and the half a renumber most easily forgets."""
    wrong = []
    for path in _lesson_files():
        match = re.search(r"^id:\s*(\S+)\s*$", path.read_text(encoding="utf-8"), re.M)
        if not match:
            wrong.append(f"{path.name}: no `id:` in the front-matter")
        elif match.group(1) != path.stem:
            wrong.append(f"{path.name}: id is {match.group(1)!r}")
    assert not wrong, "front-matter `id` must equal the filename:\n  " + "\n  ".join(wrong)


def test_every_lesson_appears_in_its_category_index() -> None:
    """A lesson nobody can find from the index is a lesson nobody reads.

    `_index.md` is the entry point the format file names, so a file that never
    got its row is written and unreachable — the same silent half-done state a
    renumber leaves if only the file moves.
    """
    missing = [
        f"{path.parent.name}/{path.name}"
        for path in _lesson_files()
        if path.name not in (path.parent / "_index.md").read_text(encoding="utf-8")
    ]
    assert not missing, "these lessons have no row in their category `_index.md`:\n  " + "\n  ".join(missing)
