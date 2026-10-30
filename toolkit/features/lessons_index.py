"""Keep the lesson indexes in step with the files, and refuse what a rewrite would hide.

The indexes used to state how many lessons exist, in three places: a total at
the top of `docs/lessons/_index.md`, a column per category in its table, and a
heading in each category's `_index.md`. Hand-written, they drifted, so #1649
derived them here and a pre-commit hook applied the result.

Derived or not, each count was a **shared mutable line** that every lesson PR
rewrote. Two PRs that each add a lesson rewrite it from different bases, and git
merges the two edits as text without a conflict. Master broke that way twice on
2026-10-18 (#2525), each time with every PR green on its own.

So the counts are gone (#2525). The docstring this replaces kept them on the
ground that removing them would make the guard vacuous. It does not. The guard
was never the number: `tests/test_lesson_index_integrity.py` asserts that every
lesson file has a row, every row points at a file, and no row appears twice
(DEBT-012, #1469). Together those fix the count, so a stated number checked
nothing they do not. The failure #1649 names, a counter that balanced while a
row was dropped, is the one the row tests catch and the counter could not.
`TestNoCommittedCount` refuses a count that comes back.

What remains derived is each category's row order, newest first (#1912). Adding
a lesson now touches only its own row, so two such PRs either merge correctly or
conflict visibly.

## Some corpora must not be rewritten at all (#1678 AC5)

`reconcile()` answers one question: *are the rows in order?* Two conditions
make any rewrite of the indexes harmful, because it reports success over a
broken corpus. Both were measured while the indexes still held counts:

- **two lessons share a number.** A lesson number is a citation, so a duplicate
  makes two documents answer to one reference. Measured 2026-09-05: two branches
  each took `439` from the same master (#1683 and #1695). From a counter's point
  of view that is an ordinary `438 declared, 439 files`, so `--fix` writes 439
  and reports success, and the local gate goes green over a corpus with two
  lesson 439s.
- **a lesson committed at HEAD is gone from the tree.** Measured the same day,
  on this very branch: a `git reset --soft` onto a moved base staged the deletion
  of a peer's lesson, and the pre-commit hook adjusted the counters *downward*
  and printed `Passed`. A correct count over a corpus missing a document is the
  self-consistent lie #1649 already names.

- **an index still holds conflict markers** (#1700). Measured 2026-09-06 on
  #1696: `--fix` rewrote the HEAD side of a conflicted `_index.md`, reported
  success, and the lesson tests passed, because the markers sit between rows
  that are each well formed. Committing then stages the markers behind a green
  suite. The remedy is to finish the merge, not to reorder rows, so it is a
  hazard of its own rather than a "rows out of order".

So the rows are reordered LAST, and only over a corpus that is safe to touch.
`hazards()` asks the prior question and `reconcile()` is never reached when the
answer is bad -- which is why it lives in its own function rather than inside
it.

The removal check compares against **`HEAD`, never the index**. The index is the
thing that changed: `git ls-files` on a staged deletion already reports the file
gone, so an oracle built on it sees disk == index and passes, at exactly the
moment it is needed. Verified by measurement, not by reading the manual.

When git cannot answer -- not installed, or the tree is not a repository --
`CannotCheck` is raised and the caller exits non-zero. An unanswerable question
is never reported as a pass; that rule is the whole of lesson 416 and of
`make alerts` raising instead of returning an empty list.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import shutil
import subprocess

#: `| 429 | [title](lesson-429-....md) | 2026-09-04 |`
LESSON_ROW = re.compile(r"^\| \d+ \| \[.*\]\((?P<file>lesson-[^)]+\.md)\) \| (?P<date>\d{4}-\d{2}-\d{2}) \|")


#: `lesson-439-a-mock-of-an-unmeasured-boundary-certifies-the-belief.md`
#:
#: The slug is captured because it is what tells a RENUMBER from a REMOVAL. A
#: renumber is a delete plus an add (that is how the duplicate 439 was resolved:
#: the later one became 440), so a removal check with no slug arm would wall off
#: the one operation the corpus most often needs -- and a gate with no door is a
#: gate people learn to pass with `--no-verify`.
LESSON_NAME = re.compile(r"^lesson-(?P<number>\d+)-(?P<slug>.+)\.md$")


#: The lines git writes into a conflicted file: ours, the base (diff3/zdiff3),
#: the separator and theirs. Seven characters at column 0, which no table row,
#: heading or prose line in an index starts with.
CONFLICT_MARKER = re.compile(r"^(?:[<>|]{7}(?: .*)?|={7})$")


class CannotCheck(Exception):
    """The corpus could not be examined, so no verdict about it is available.

    Distinct from a hazard: a hazard is something true about the corpus, this is
    the absence of an answer. Callers must exit non-zero on it. Reporting it as a
    pass is the failure mode every guard in this repository is written against.
    """


@dataclasses.dataclass(frozen=True)
class Hazard:
    """A condition that makes rewriting the indexes the wrong operation.

    `remedy` exists because the pre-push hint is half of what this AC is about:
    the hook used to print `--fix` for every failure, which for a collision is
    the instruction that makes the defect invisible. Each hazard carries the
    remedy for ITS OWN case, so no caller has to guess which case it is in.
    """

    headline: str
    detail: str
    remedy: str

    def __str__(self) -> str:
        return f"{self.headline}\n{self.detail}\n\n  {self.remedy}"


@dataclasses.dataclass(frozen=True)
class Fix:
    """One index row that was out of order."""

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


def all_lesson_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Every lesson file in the corpus, across categories.

    Globbed directly rather than walked through `category_dirs`, which requires a
    category to have an `_index.md`. A category whose index was deleted must
    still be scanned for collisions: making a hazard disappear by deleting a file
    is the shape this whole module exists to refuse.
    """
    return sorted(root.glob("*/lesson-*.md"))


def number_collisions(root: pathlib.Path) -> dict[str, list[str]]:
    """Lesson numbers claimed by more than one file, corpus-wide.

    THE single predicate for this class. `tests/test_lessons_index.py` imports it
    rather than keeping its own copy: two implementations of one rule is how one
    of them drifts, and the CI test and the local hook disagreeing about what a
    collision is would be worse than either being absent.
    """
    by_number: dict[str, list[str]] = {}
    for path in all_lesson_files(root):
        if m := LESSON_NAME.match(path.name):
            by_number.setdefault(m.group("number"), []).append(f"{path.parent.name}/{path.name}")
    return {n: sorted(paths) for n, paths in sorted(by_number.items()) if len(paths) > 1}


def relative_posix(path: pathlib.PurePath, root: pathlib.PurePath) -> str:
    """`path` relative to `root`, always with `/` separators.

    The two sides of the removal comparison come from different worlds: one from
    `git ls-tree`, which emits `/` on every platform, and one from the
    filesystem, where `str(WindowsPath(...))` emits `\\`. Comparing them raw
    makes the sets disjoint on Windows, so EVERY committed lesson reads as
    removed and the gate refuses every push -- a false positive that the Linux
    CI cannot see and that lands only on the ADR-052 Windows workstation.

    Found by review on #1714, not by a test. Which is the point of the test that
    now covers it: it builds a `PureWindowsPath` explicitly, so the assertion is
    about separators rather than about the platform running it.
    """
    return path.relative_to(root).as_posix()


def _committed_lesson_files(root: pathlib.Path) -> set[str]:
    """Lesson paths present at HEAD, relative to `root`.

    HEAD and not the index -- see the module docstring. `git -C <root> ls-tree
    -r --name-only HEAD -- .` prints paths relative to `root`, which is what
    makes the set comparable to the glob above; verified rather than assumed.
    """
    if shutil.which("git") is None:
        raise CannotCheck("git is not on PATH, so the committed corpus cannot be read")
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-r", "--name-only", "HEAD", "--", "."],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise CannotCheck(f"`git ls-tree HEAD` could not be read under {root}: {stderr.strip() or exc}") from exc
    return {line for line in completed.stdout.splitlines() if LESSON_NAME.match(pathlib.Path(line).name)}


def removed_lessons(root: pathlib.Path) -> list[str]:
    """Lessons committed at HEAD that no longer exist on disk, excluding renames.

    A renumber is a delete plus an add, and it is a legitimate, frequent
    operation -- it is how a duplicate number gets resolved. It is told apart by
    the SLUG reappearing on a file that HEAD does not have, so the door opens on
    evidence in the tree rather than on a flag someone remembers to pass. A
    retitle is the same move on the other half of the name: the NUMBER
    reappears with a new slug. A duplicate number that this lets through is
    still refused, by `number_collisions`.

    The `not in committed` half is load-bearing and is not belt-and-braces. If
    the door merely asked "does this slug exist somewhere on disk", then any
    OTHER lesson that happened to share the slug -- one already committed, and
    untouched by this change -- would excuse the deletion. The excuse has to be
    the arrival of a new file, because that is what a renumber actually is.
    """
    committed = _committed_lesson_files(root)
    on_disk = {relative_posix(p, root) for p in all_lesson_files(root)}
    arrived = [
        m
        for p in all_lesson_files(root)
        if relative_posix(p, root) not in committed and (m := LESSON_NAME.match(p.name))
    ]
    arrived_slugs = {m.group("slug") for m in arrived}
    arrived_numbers = {int(m.group("number")) for m in arrived}

    gone = []
    for rel in sorted(committed - on_disk):
        m = LESSON_NAME.match(pathlib.PurePosixPath(rel).name)
        if m and (m.group("slug") in arrived_slugs or int(m.group("number")) in arrived_numbers):
            continue  # renumbered or retitled, not removed
        gone.append(rel)
    return gone


def unmerged_indexes(root: pathlib.Path) -> dict[str, list[int]]:
    """Index files holding conflict markers, with the line numbers of each marker.

    THE single predicate for this class, imported by
    `tests/test_lesson_index_integrity.py` as `number_collisions` is by its test.
    Every index is read, the top level included, because a reader navigates
    through all of them and a marker in any one is an unfinished merge.
    """
    found: dict[str, list[int]] = {}
    for index in [root / "_index.md", *sorted(root.glob("*/_index.md"))]:
        if not index.exists():
            continue
        lines = index.read_text(encoding="utf-8").splitlines()
        if at := [n for n, line in enumerate(lines, start=1) if CONFLICT_MARKER.match(line)]:
            found[relative_posix(index, root)] = at
    return found


def hazards(root: pathlib.Path, allow_removal: bool = False) -> list[Hazard]:
    """Conditions under which rewriting the indexes is the wrong operation.

    Called BEFORE `reconcile`, never inside it: "is this corpus safe to touch"
    is a different question from "are the rows in order", and answering the
    second one first is what let a green gate sit over a duplicated number.

    Raises `CannotCheck` when the removal arm cannot be evaluated. Deliberately
    not downgraded to "no hazards found".
    """
    found: list[Hazard] = []

    if unmerged := unmerged_indexes(root):
        found.append(
            Hazard(
                headline=f"{len(unmerged)} lesson index file(s) hold conflict markers: the merge is not finished.",
                detail="\n".join(f"    {rel}: line(s) {', '.join(map(str, at))}" for rel, at in unmerged.items())
                + "\n\n  The rows on either side of a marker are well formed, so reordering them"
                + "\n  would succeed and leave the markers in the file, and the row tests would"
                + "\n  pass over them (#1700).",
                remedy="Resolve each conflict in the file(s) above and `git add` them, then re-run.",
            )
        )

    if collisions := number_collisions(root):
        found.append(
            Hazard(
                headline=f"{len(collisions)} lesson number(s) are claimed by more than one file.",
                detail="\n".join(f"    {n}: {', '.join(paths)}" for n, paths in collisions.items())
                + "\n\n  A lesson number is a citation, so two documents cannot answer to one."
                + "\n  This happens when two branches each take `the next free number` from"
                + "\n  the same master; neither is wrong alone, the duplicate exists only in"
                + "\n  the merge. Rewriting the indexes would leave the collision in place"
                + "\n  and report success, which is why this refuses instead.",
                remedy="Resolve it as docs/lessons/_format.md prescribes: the one that landed "
                "FIRST keeps the number, the later one moves to the next free one, and both "
                "indexes follow. Then re-run.",
            )
        )

    removed = removed_lessons(root)
    if removed and not allow_removal:
        found.append(
            Hazard(
                headline=f"{len(removed)} lesson(s) committed at HEAD are missing from the tree.",
                detail="\n".join(f"    {rel}" for rel in removed)
                + "\n\n  Compared against HEAD rather than the index, because a staged deletion"
                + "\n  is already absent from the index -- an oracle built on it would pass"
                + "\n  exactly here. A rebase or a `reset --soft` onto a moved base does this"
                + "\n  silently, and a rewrite would report an index that agrees with a"
                + "\n  corpus that lost a document.",
                remedy="If this is unintended, restore them (`git checkout origin/master -- "
                "docs/lessons/`) and re-run. If the removal IS the change you mean to make, "
                "say so with --allow-removal.",
            )
        )

    return found


def _row_key(row: str) -> tuple[str, int]:
    m = LESSON_ROW.match(row)
    assert m, row
    return m.group("date"), int(row.split("|")[1])


def _order_rows(path: pathlib.Path, apply: bool) -> list[Fix]:
    """Order a category's rows newest first: by date, then by number within a date (#1912).

    Rows keep the line endings of the positions they move into, so a last row
    with no trailing newline cannot glue itself to the next one.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    at = [i for i, line in enumerate(lines) if LESSON_ROW.match(line)]
    rows = sorted((lines[i].rstrip("\n") for i in at), key=_row_key, reverse=True)
    fixes: list[Fix] = []
    for i, row in zip(at, rows, strict=True):
        moved = row + lines[i][len(lines[i].rstrip("\n")) :]
        if moved != lines[i]:
            fixes.append(Fix(path=path, line_number=i + 1, was=lines[i], now=moved))
            lines[i] = moved
    if fixes and apply:
        path.write_text("".join(lines), encoding="utf-8")
    return fixes


def reconcile(root: pathlib.Path, apply: bool = False) -> list[Fix]:
    """Bring every category's rows into newest-first order.

    Returns the fixes needed; writes them when `apply`. An empty list means the
    indexes are already in order. No count is written anywhere (#2525).
    """
    fixes: list[Fix] = []
    for cat in category_dirs(root):
        fixes += _order_rows(cat / "_index.md", apply)
    return fixes
