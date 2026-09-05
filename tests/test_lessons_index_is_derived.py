"""The lesson index counters must be derived, and the deriver must actually derive.

`tests/test_lesson_index_integrity.py` already asserts the counters match the
files. It is the red light. This file is about the thing that keeps them from
going wrong in the first place (#1649), and about the deriver itself -- because
a reconciler that found nothing would satisfy every "counters match" test in the
repo while doing nothing at all.

Every fixture here builds a lesson tree in tmp_path rather than reading the real
one: a test that only ever sees a correct corpus cannot tell "agrees" from
"never looked".
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from toolkit.features import lessons_index

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REAL_LESSONS = REPO_ROOT / "docs" / "lessons"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
PRE_PUSH = REPO_ROOT / ".github" / "hooks" / "pre-push.sh"


def _tree(root: pathlib.Path, categories: dict[str, int], total: int | None = None) -> pathlib.Path:
    """A miniature lessons tree whose declared numbers are whatever we say."""
    root.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"| [{slug}]({slug}/_index.md) | {n} | Scope for {slug} |" for slug, n in categories.items()
    )
    stated = sum(categories.values()) if total is None else total
    (root / "_index.md").write_text(
        "# Lessons\n\n"
        f"{stated} lessons, one file each. Newest: 2026-01-01. Open a category for its list.\n\n"
        "| Category | # | Scope |\n|---|---|---|\n" + rows + "\n",
        encoding="utf-8",
    )
    n = 100
    for slug, declared in categories.items():
        cat = root / slug
        cat.mkdir(exist_ok=True)
        lines = []
        for _ in range(declared):
            n += 1
            fname = f"lesson-{n}-a-lesson.md"
            (cat / fname).write_text("---\nid: x\n---\nbody\n", encoding="utf-8")
            # One fixed date across the fixture: the header below states the
            # same one, so a tree built here is internally consistent and any
            # fix the deriver reports is about a count, not about the date.
            lines.append(f"| {n} | [A lesson]({fname}) | 2026-01-01 |")
        (cat / "_index.md").write_text(
            f"# {slug}\n\n{declared} lessons, newest first. Back to [all categories](../_index.md).\n\n"
            "| # | Lesson | Date |\n|---|---|---|\n" + "\n".join(lines) + "\n",
            encoding="utf-8",
        )
    return root


class TestTheDeriverActuallyDerives:
    """Floors. A reconciler that returns nothing agrees with every corpus."""

    def test_a_correct_tree_needs_no_fixes(self, tmp_path: pathlib.Path) -> None:
        root = _tree(tmp_path / "lessons", {"alpha": 3, "beta": 2})
        assert lessons_index.reconcile(root) == []

    def test_a_wrong_total_is_found(self, tmp_path: pathlib.Path) -> None:
        root = _tree(tmp_path / "lessons", {"alpha": 3, "beta": 2}, total=99)
        fixes = lessons_index.reconcile(root)
        assert fixes, "a total of 99 over 5 files was not detected"
        assert any("5 lessons" in f.now for f in fixes)

    def test_a_wrong_category_count_is_found(self, tmp_path: pathlib.Path) -> None:
        root = _tree(tmp_path / "lessons", {"alpha": 3, "beta": 2})
        cat = root / "alpha" / "_index.md"
        cat.write_text(cat.read_text().replace("3 lessons, newest first", "7 lessons, newest first"))
        assert any(f.path == cat for f in lessons_index.reconcile(root))

    def test_the_arrival_of_one_lesson_moves_three_counters(self, tmp_path: pathlib.Path) -> None:
        """The real scenario: a merge brings a lesson in and touches no counter.

        Three numbers go stale at once -- the total, that category's column in
        the top-level table, and the category's own heading. A deriver that
        fixed only the total would leave the other two, and the integrity test
        would still go red.
        """
        root = _tree(tmp_path / "lessons", {"alpha": 3, "beta": 2})
        (root / "alpha" / "lesson-900-arrived-by-merge.md").write_text("---\nid: x\n---\n")
        fixes = lessons_index.reconcile(root)
        assert len(fixes) == 3, f"expected total + column + heading, got {[str(f) for f in fixes]}"

    def test_applying_makes_a_second_run_clean(self, tmp_path: pathlib.Path) -> None:
        """Idempotence, and the property the hook depends on: a commit that
        triggers a rewrite must not trigger another one forever."""
        root = _tree(tmp_path / "lessons", {"alpha": 3, "beta": 2}, total=99)
        assert lessons_index.reconcile(root, apply=True)
        assert lessons_index.reconcile(root) == []

    def test_check_mode_does_not_write(self, tmp_path: pathlib.Path) -> None:
        root = _tree(tmp_path / "lessons", {"alpha": 3, "beta": 2}, total=99)
        before = (root / "_index.md").read_text()
        lessons_index.reconcile(root, apply=False)
        assert (root / "_index.md").read_text() == before


class TestTheDeriverReadsTheRealCorpus:
    """The fixtures above prove the logic; this proves it fits this repo.

    A deriver whose regexes stopped matching the real index would pass every
    tmp_path test and silently do nothing where it counts.
    """

    def test_the_real_index_is_parsed_at_all(self) -> None:
        cats = lessons_index.category_dirs(REAL_LESSONS)
        assert len(cats) >= 10, f"parsed {len(cats)} categories from the real tree"
        assert sum(len(lessons_index.lesson_files(c)) for c in cats) >= 300

    def test_the_real_index_currently_agrees(self) -> None:
        """If this fails, the committed indexes are stale — run
        `toolkit tools lessons-index --fix`."""
        fixes = lessons_index.reconcile(REAL_LESSONS)
        assert not fixes, "committed counters disagree with the files:\n" + "\n".join(str(f) for f in fixes)

    def test_the_newest_date_comes_from_rows_not_mtimes(self) -> None:
        """mtime records when a file was last touched — a rebase or a typo fix
        moves it — while the index is stating when the newest lesson was
        written. Reading mtimes would make the date drift on every checkout."""
        assert lessons_index.newest_date(REAL_LESSONS) is not None


class TestTheHookIsWired:
    """A deriver nobody runs is a script, not a mechanism."""

    def test_the_hook_exists_and_fixes(self) -> None:
        cfg = yaml.safe_load(PRE_COMMIT.read_text())
        local = [r for r in cfg["repos"] if r.get("repo") == "local"]
        hooks = [h for r in local for h in r["hooks"] if h["id"] == "lessons-index-counts"]
        assert hooks, "the lessons-index-counts hook is not declared"
        assert "--fix" in hooks[0]["entry"], "the hook must rewrite, not merely report"

    def test_the_hook_watches_the_lessons_tree(self) -> None:
        """`files:` decides whether the commit-time hook sees the change."""
        cfg = yaml.safe_load(PRE_COMMIT.read_text())
        hook = next(
            h for r in cfg["repos"] if r.get("repo") == "local" for h in r["hooks"] if h["id"] == "lessons-index-counts"
        )
        import re

        pattern = re.compile(hook["files"])
        assert pattern.search("docs/lessons/observability/lesson-999-x.md")
        assert pattern.search("docs/lessons/_index.md")
        assert not pattern.search("toolkit/features/lessons_index.py"), "the hook should not fire on unrelated files"

    def test_a_second_stage_covers_the_merge_route(self) -> None:
        """The commit-time hook structurally cannot see a clean merge.

        Measured: git does not run pre-commit for a merge that resolves without
        conflict. Merging a branch carrying a new lesson gave `Merge made by
        the 'ort' strategy`, no hook output, 433 files and 432 declared -- the
        defect arriving by the very route that caused all four collisions,
        straight past the hook meant to stop it.

        An earlier version of this change claimed the opposite in its own
        comment. So this pins the second stage, and pins that it CHECKS rather
        than fixes: rewriting files during a push would leave the working tree
        ahead of what is being pushed.
        """
        cfg = yaml.safe_load(PRE_COMMIT.read_text())
        hooks = {h["id"]: h for r in cfg["repos"] if r.get("repo") == "local" for h in r["hooks"]}

        commit_hook = hooks["lessons-index-counts"]
        assert commit_hook.get("stages") == ["pre-commit"]
        assert "--fix" in commit_hook["entry"]

        # And it is NOT declared as a pre-commit pre-push stage, which would be
        # configuration nothing runs: this repo sets `core.hooksPath` and its
        # pre-push is its own script, which never invokes pre-commit.
        assert not any(
            "pre-push" in (h.get("stages") or []) for h in hooks.values()
        ), "a pre-push stage declared here would never execute -- core.hooksPath points at .github/hooks"

        script = PRE_PUSH.read_text()
        assert "toolkit tools lessons-index" in script, (
            "nothing guards the merge route: a clean merge skips pre-commit entirely, "
            "so the push-time check must live in the script git actually runs"
        )
        # The EXECUTED invocations, not the prose. The script legitimately
        # mentions `--fix` twice -- once in its comment and once in the remedy
        # it prints for the user -- and an earlier version of this assertion
        # scanned the raw text and failed on the comment. Same defect as
        # lesson-432: a check that cannot tell a warning from an instance.
        executed = [
            line
            for line in script.splitlines()
            if "toolkit tools lessons-index" in line and not line.lstrip().startswith(("#", "echo"))
        ]
        assert executed, "the command is mentioned but never run"
        assert all("--check" in line for line in executed), (
            f"the push-time check must report, not rewrite the tree mid-push: {executed}"
        )


@pytest.mark.parametrize(
    "line,expected",
    [
        ("433 lessons, one file each. Newest: 2026-09-05. Open a category for its list.", True),
        ("| [observability](observability/_index.md) | 17 | Metrics, logs, alerting |", False),
        ("New lessons: see [`_format.md`](_format.md) — one file per lesson, appended", False),
    ],
)
def test_the_total_pattern_matches_only_the_total(line: str, expected: bool) -> None:
    """A pattern loose enough to match prose would rewrite the prose."""
    assert bool(lessons_index.TOTAL_LINE.match(line)) is expected
