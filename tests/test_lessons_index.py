"""The lessons corpus is consistent: unique numbers, matching ids, indexed rows.

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

import collections
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
LESSONS = REPO / "docs/lessons"


def _lesson_files() -> list[pathlib.Path]:
    return sorted(LESSONS.glob("*/lesson-*.md"))


def _number(path: pathlib.Path) -> str:
    match = re.match(r"lesson-(\d+)-", path.name)
    assert match, f"{path.name} does not start with `lesson-NNN-`"
    return match.group(1)


def test_the_scan_finds_the_corpus() -> None:
    """Without this, a moved directory turns every assertion below into a pass."""
    files = _lesson_files()
    assert len(files) > 300, (
        f"only {len(files)} lesson files found under {LESSONS}; the scan has drifted "
        f"and the checks below are asserting nothing"
    )


def test_no_two_lessons_share_a_number() -> None:
    """A lesson number is a citation. Two documents cannot answer to one."""
    by_number: dict[str, list[str]] = collections.defaultdict(list)
    for path in _lesson_files():
        by_number[_number(path)].append(f"{path.parent.name}/{path.name}")

    collisions = {n: paths for n, paths in by_number.items() if len(paths) > 1}
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
    assert not missing, (
        "these lessons have no row in their category `_index.md`:\n  " + "\n  ".join(missing)
    )


def test_the_declared_corpus_count_matches_the_files_on_disk() -> None:
    """`_index.md` opens with "N lessons, one file each" — and N must be true.

    Nothing checked it. `test_the_scan_finds_the_corpus` asserts only `> 300`,
    so the number could drift silently for as long as nobody counted by hand.

    Found sideways, 2026-08-22: a reviewer claimed the count was wrong on a PR
    where it was right, having confused the lesson NUMBER (370) with the COUNT
    (369). The claim was false — numbers are never reused, so gaps make the
    highest number exceed the total — but checking it revealed that the
    assertion it assumed existed did not.

    The count is a claim about the corpus. A claim in a file nothing verifies is
    a comment.
    """
    declared = re.search(r"(\d+) lessons, one file each", (LESSONS / "_index.md").read_text(encoding="utf-8"))
    assert declared, "`_index.md` no longer opens with the corpus count; update this guard with it"

    actual = len(_lesson_files())
    assert int(declared.group(1)) == actual, (
        f"`docs/lessons/_index.md` declares {declared.group(1)} lessons but {actual} files exist. "
        "The count is the number of FILES, not the highest lesson number — numbers are "
        "never reused, so gaps make the highest number exceed the total."
    )
