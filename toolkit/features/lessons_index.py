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

## Counters are not the only way a corpus goes wrong (#1678 AC5)

`reconcile()` answers exactly one question: *do the declared counts match the
files?* Two other conditions produce the same symptom -- a count that disagrees
-- and for both of them recounting is not merely useless but actively harmful:

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

So the counters are checked LAST, and only over a corpus that is safe to count.
`hazards()` asks the prior question and `reconcile()` is never reached when the
answer is bad -- which is why it lives in its own function rather than inside
it. The two questions are different: *is this corpus countable* comes before
*what do the counters say*.

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
from collections.abc import Callable

#: `433 lessons, one file each. Newest: 2026-09-05. Open a category for its list.`
#:
#: `rest` exists so the rewrite REPLACES the two numbers and preserves whatever
#: else the line says. Rewriting the whole line from a template would silently
#: drop any wording added after the date -- the deriver would be destroying
#: prose it does not own, once, invisibly, on somebody else's edit.
TOTAL_LINE = re.compile(r"^(?P<n>\d+) lessons, one file each\. Newest: (?P<date>\d{4}-\d{2}-\d{2})\.(?P<rest>.*)$")

#: `| [observability](observability/_index.md) | 17 | Metrics, logs, alerting |`
CATEGORY_ROW = re.compile(r"^\| \[(?P<slug>[a-z-]+)\]\((?P=slug)/_index\.md\) \| (?P<n>\d+) \|")

#: `17 lessons, newest first. Back to [all categories](../_index.md).`
CATEGORY_LINE = re.compile(r"^(?P<n>\d+) lessons, newest first\.")

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


class CannotCheck(Exception):
    """The corpus could not be examined, so no verdict about it is available.

    Distinct from a hazard: a hazard is something true about the corpus, this is
    the absence of an answer. Callers must exit non-zero on it. Reporting it as a
    pass is the failure mode every guard in this repository is written against.
    """


@dataclasses.dataclass(frozen=True)
class Hazard:
    """A condition that makes recounting the wrong operation.

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


def hazards(root: pathlib.Path, allow_removal: bool = False) -> list[Hazard]:
    """Conditions under which recounting is the wrong operation.

    Called BEFORE `reconcile`, never inside it: "is this corpus safe to count"
    is a different question from "what do the counters say", and answering the
    second one first is what let a green gate sit over a duplicated number.

    Raises `CannotCheck` when the removal arm cannot be evaluated. Deliberately
    not downgraded to "no hazards found".
    """
    found: list[Hazard] = []

    if collisions := number_collisions(root):
        found.append(
            Hazard(
                headline=f"{len(collisions)} lesson number(s) are claimed by more than one file.",
                detail="\n".join(f"    {n}: {', '.join(paths)}" for n, paths in collisions.items())
                + "\n\n  A lesson number is a citation, so two documents cannot answer to one."
                + "\n  This happens when two branches each take `the next free number` from"
                + "\n  the same master; neither is wrong alone, the duplicate exists only in"
                + "\n  the merge. Recounting would make the total correct and leave the"
                + "\n  collision in place, which is why this refuses instead.",
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
                + "\n  silently, and recounting would write the smaller number and call it"
                + "\n  correct: an index that agrees with a corpus that lost a document.",
                remedy="If this is unintended, restore them (`git checkout origin/master -- "
                "docs/lessons/`) and re-run. If the removal IS the change you mean to make, "
                "say so with --allow-removal.",
            )
        )

    return found


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
        if m := TOTAL_LINE.match(line.rstrip("\n")):
            # `newest or ...` keeps the committed date when no rows exist at
            # all, rather than writing the string "None" into the index.
            date = newest or m.group("date")
            return f"{total} lessons, one file each. Newest: {date}.{m.group('rest')}\n"
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
