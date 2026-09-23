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
import subprocess

import pytest
import yaml
from typer.testing import CliRunner

from toolkit.cli.tools import app as tools_app
from toolkit.features import lessons_index

runner = CliRunner()

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REAL_LESSONS = REPO_ROOT / "docs" / "lessons"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
PRE_PUSH = REPO_ROOT / ".github" / "hooks" / "pre-push.sh"


def _tree(root: pathlib.Path, categories: dict[str, int], total: int | None = None) -> pathlib.Path:
    """A miniature lessons tree whose declared numbers are whatever we say."""
    root.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"| [{slug}]({slug}/_index.md) | {n} | Scope for {slug} |" for slug, n in categories.items())
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
        assert not any("pre-push" in (h.get("stages") or []) for h in hooks.values()), (
            "a pre-push stage declared here would never execute -- core.hooksPath points at .github/hooks"
        )

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


class TestTheRewriteOnlyTouchesTheNumbers:
    """It rewrites a line it does not own the whole of.

    Raised in review: the pattern is anchored at the start and the replacement
    was built from a fixed template, so any wording added after the date would
    be discarded — once, invisibly, on somebody else's edit. The deriver has no
    business editing prose.
    """

    def test_trailing_prose_survives(self, tmp_path: pathlib.Path) -> None:
        root = _tree(tmp_path / "lessons", {"alpha": 3}, total=99)
        top = root / "_index.md"
        top.write_text(
            top.read_text().replace(
                "Open a category for its list.",
                "Open a category for its list. Counts are derived; do not edit by hand.",
            )
        )
        lessons_index.reconcile(root, apply=True)
        line = next(ln for ln in top.read_text().splitlines() if "lessons, one file each" in ln)
        assert line.startswith("3 lessons, one file each."), line
        assert line.endswith("Counts are derived; do not edit by hand."), (
            f"the rewrite dropped wording it does not own: {line!r}"
        )

    def test_an_empty_corpus_does_not_write_the_word_none(self, tmp_path: pathlib.Path) -> None:
        """Also raised in review, and already handled — pinned so it stays that
        way. `newest_date` returns None with no rows, and the committed date is
        kept rather than interpolated."""
        root = tmp_path / "lessons"
        root.mkdir()
        (root / "_index.md").write_text(
            "# Lessons\n\n0 lessons, one file each. Newest: 2026-01-01. Open a category for its list.\n"
        )
        assert lessons_index.newest_date(root) is None
        lessons_index.reconcile(root, apply=True)
        assert "None" not in (root / "_index.md").read_text()


# =============================================================================
# #1678 AC5 — the gate must refuse what it cannot fix
# =============================================================================
#
# The counters are not the only way this corpus goes wrong, and for two other
# conditions recounting is not merely useless, it is the operation that hides
# them. Both were measured on 2026-09-05:
#
#   - two branches each took the number 439 from the same master (#1683, #1695);
#     `--fix` would write the larger total and report success over a corpus with
#     two lesson 439s;
#   - a `git reset --soft` onto a moved base staged the deletion of a peer's
#     lesson, and the pre-commit hook adjusted the counters DOWNWARD and printed
#     `Passed`.
#
# Every test below builds its own tree. The git ones build a real repository,
# because the distinction they turn on -- HEAD versus the index -- does not
# exist in a fake.


def _git(root: pathlib.Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repo_with_lessons(tmp_path: pathlib.Path, names: dict[str, list[str]]) -> pathlib.Path:
    """A real git repository whose committed corpus is exactly `names`.

    `names` maps a category to its lesson filenames, so a test can give each
    lesson a DISTINCT slug -- which `_tree` above deliberately does not, and
    which the renumber door turns on.
    """
    repo = tmp_path / "repo"
    lessons = repo / "docs" / "lessons"
    for category, files in names.items():
        (lessons / category).mkdir(parents=True, exist_ok=True)
        rows = []
        for fname in files:
            (lessons / category / fname).write_text("---\nid: x\n---\nbody\n", encoding="utf-8")
            rows.append(f"| 1 | [A lesson]({fname}) | 2026-01-01 |")
        (lessons / category / "_index.md").write_text(
            f"# {category}\n\n{len(files)} lessons, newest first.\n\n"
            "| # | Lesson | Date |\n|---|---|---|\n" + "\n".join(rows) + "\n",
            encoding="utf-8",
        )
    total = sum(len(f) for f in names.values())
    rows = "\n".join(f"| [{c}]({c}/_index.md) | {len(f)} | Scope |" for c, f in names.items())
    (lessons / "_index.md").write_text(
        f"# Lessons\n\n{total} lessons, one file each. Newest: 2026-01-01. Open a category.\n\n"
        "| Category | # | Scope |\n|---|---|---|\n" + rows + "\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "corpus")
    return lessons


class TestADuplicatedNumberIsRefused:
    """The class the counters cannot see: two documents answering to one citation."""

    def test_the_predicate_names_both_files(self, tmp_path: pathlib.Path) -> None:
        lessons = _repo_with_lessons(
            tmp_path,
            {"alpha": ["lesson-439-a-ceiling.md"], "beta": ["lesson-439-a-mock.md"]},
        )
        collisions = lessons_index.number_collisions(lessons)
        assert collisions == {"439": ["alpha/lesson-439-a-ceiling.md", "beta/lesson-439-a-mock.md"]}

    def test_a_clean_corpus_has_no_collisions(self, tmp_path: pathlib.Path) -> None:
        """The floor. A predicate that never fires would pass every test above."""
        lessons = _repo_with_lessons(
            tmp_path,
            {"alpha": ["lesson-439-a-ceiling.md"], "beta": ["lesson-440-a-mock.md"]},
        )
        assert lessons_index.number_collisions(lessons) == {}
        assert lessons_index.hazards(lessons) == []

    def test_it_is_a_hazard_not_a_counter_fix(self, tmp_path: pathlib.Path) -> None:
        lessons = _repo_with_lessons(
            tmp_path,
            {"alpha": ["lesson-439-a-ceiling.md"], "beta": ["lesson-439-a-mock.md"]},
        )
        found = lessons_index.hazards(lessons)
        assert len(found) == 1
        assert "claimed by more than one file" in found[0].headline
        assert "439" in found[0].detail

    def test_fix_writes_nothing_on_a_colliding_tree(self, tmp_path: pathlib.Path) -> None:
        """The whole point of AC5: a stale counter AND a collision at once.

        `--fix` here would make the total correct and leave two lesson 439s in
        place, then report success. The counters must come out untouched.
        """
        lessons = _repo_with_lessons(
            tmp_path,
            {"alpha": ["lesson-439-a-ceiling.md"], "beta": ["lesson-439-a-mock.md"]},
        )
        top = lessons / "_index.md"
        top.write_text(top.read_text().replace("2 lessons, one file each", "7 lessons, one file each"))
        before = top.read_text()

        result = runner.invoke(tools_app, ["lessons-index", "--root", str(lessons), "--fix"])

        assert result.exit_code == 2, result.output
        assert top.read_text() == before, "the counters were rewritten over a colliding corpus"


class TestALessonThatHeadHasAndTheTreeDoesNotIsRefused:
    """Measured on this very branch: the counters were adjusted DOWNWARD and passed."""

    def test_a_deleted_lesson_is_found(self, tmp_path: pathlib.Path) -> None:
        lessons = _repo_with_lessons(tmp_path, {"alpha": ["lesson-1-one.md", "lesson-2-two.md"]})
        (lessons / "alpha" / "lesson-2-two.md").unlink()
        assert lessons_index.removed_lessons(lessons) == ["alpha/lesson-2-two.md"]

    def test_a_STAGED_deletion_is_still_found(self, tmp_path: pathlib.Path) -> None:
        """The oracle must be HEAD, never the index.

        `git ls-files` reports the file already gone once the deletion is staged
        -- which is exactly the state a `reset --soft` onto a moved base leaves.
        An oracle built on the index sees disk == index and passes at precisely
        the moment it is needed. Measured before this code was written.
        """
        lessons = _repo_with_lessons(tmp_path, {"alpha": ["lesson-1-one.md", "lesson-2-two.md"]})
        repo = lessons.parents[1]
        _git(repo, "rm", "-q", "docs/lessons/alpha/lesson-2-two.md")

        staged = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "docs/lessons/alpha/lesson-2-two.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert staged == "", "fixture is not exercising the case: the index still lists the file"

        assert lessons_index.removed_lessons(lessons) == ["alpha/lesson-2-two.md"]

    def test_a_renumber_is_not_a_removal(self, tmp_path: pathlib.Path) -> None:
        """The door. A renumber is a delete plus an add, and it is how a
        duplicate number gets resolved -- refusing it would send the next person
        who renumbers straight to `--no-verify`."""
        lessons = _repo_with_lessons(tmp_path, {"alpha": ["lesson-439-a-mock.md"]})
        (lessons / "alpha" / "lesson-439-a-mock.md").unlink()
        (lessons / "alpha" / "lesson-440-a-mock.md").write_text("---\nid: x\n---\nbody\n", encoding="utf-8")
        assert lessons_index.removed_lessons(lessons) == []

    def test_an_untouched_file_sharing_the_slug_does_not_excuse_a_deletion(self, tmp_path: pathlib.Path) -> None:
        """The `not in committed` half of the door.

        If the excuse were merely "some file on disk has this slug", any other
        lesson that happened to share it -- already committed, untouched by this
        change -- would license the deletion. The excuse must be the ARRIVAL of a
        file, which is what a renumber is.
        """
        lessons = _repo_with_lessons(
            tmp_path,
            {"alpha": ["lesson-1-a-mock.md"], "beta": ["lesson-2-a-mock.md"]},
        )
        (lessons / "alpha" / "lesson-1-a-mock.md").unlink()
        assert lessons_index.removed_lessons(lessons) == ["alpha/lesson-1-a-mock.md"]

    def test_fix_writes_nothing_when_a_lesson_disappeared(self, tmp_path: pathlib.Path) -> None:
        lessons = _repo_with_lessons(tmp_path, {"alpha": ["lesson-1-one.md", "lesson-2-two.md"]})
        (lessons / "alpha" / "lesson-2-two.md").unlink()
        top = lessons / "_index.md"
        before = top.read_text()

        result = runner.invoke(tools_app, ["lessons-index", "--root", str(lessons), "--fix"])

        assert result.exit_code == 2, result.output
        assert top.read_text() == before, "the counters were adjusted downward over a shrunken corpus"

    def test_allow_removal_opens_the_door(self, tmp_path: pathlib.Path) -> None:
        """A deliberate deletion must have an exit, or the gate gets --no-verify'd."""
        lessons = _repo_with_lessons(tmp_path, {"alpha": ["lesson-1-one.md", "lesson-2-two.md"]})
        (lessons / "alpha" / "lesson-2-two.md").unlink()

        assert lessons_index.hazards(lessons, allow_removal=True) == []

        result = runner.invoke(tools_app, ["lessons-index", "--root", str(lessons), "--fix", "--allow-removal"])
        assert result.exit_code == 1, result.output  # counters rewritten
        assert "1 lessons, one file each" in (lessons / "_index.md").read_text()


class TestAnUnanswerableQuestionIsNotAPass:
    """CANNOT CHECK is its own verdict, with its own exit code."""

    def test_a_tree_outside_a_repository_raises(self, tmp_path: pathlib.Path) -> None:
        root = _tree(tmp_path / "lessons", {"alpha": 2})
        with pytest.raises(lessons_index.CannotCheck):
            lessons_index.hazards(root)

    def test_the_cli_exits_three_and_says_so(self, tmp_path: pathlib.Path) -> None:
        root = _tree(tmp_path / "lessons", {"alpha": 2})
        result = runner.invoke(tools_app, ["lessons-index", "--root", str(root), "--check"])
        assert result.exit_code == 3, result.output
        assert "CANNOT CHECK" in result.output

    def test_no_git_on_path_is_cannot_check_not_clean(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing tool must never resolve to a clean bill of health."""
        lessons = _repo_with_lessons(tmp_path, {"alpha": ["lesson-1-one.md"]})
        monkeypatch.setattr(lessons_index.shutil, "which", lambda _: None)
        with pytest.raises(lessons_index.CannotCheck, match="git is not on PATH"):
            lessons_index.hazards(lessons)


class TestTheTwoSidesOfTheComparisonUseTheSameSeparator:
    """Raised in review on #1714, and a false positive Linux CI cannot see.

    `git ls-tree` emits `/` on every platform; `str(WindowsPath(...))` emits
    `\\`. Compared raw, the two sets are disjoint on Windows, so every committed
    lesson reads as removed and the gate refuses every push — on the ADR-052
    Windows workstation only.
    """

    def test_a_windows_path_still_yields_a_posix_relative_path(self) -> None:
        """Built from `PureWindowsPath` explicitly, so this asserts something
        about separators rather than about the platform running the test. On a
        raw `str(p.relative_to(root))` it fails here, on Linux."""
        root = pathlib.PureWindowsPath(r"C:\repo\docs\lessons")
        path = pathlib.PureWindowsPath(r"C:\repo\docs\lessons\alpha\lesson-1-one.md")
        assert lessons_index.relative_posix(path, root) == "alpha/lesson-1-one.md"

    def test_it_matches_what_git_prints(self, tmp_path: pathlib.Path) -> None:
        """The other half: the disk side must equal the git side for an unchanged
        corpus, or `committed - on_disk` is every lesson in the repository."""
        lessons = _repo_with_lessons(tmp_path, {"alpha": ["lesson-1-one.md", "lesson-2-two.md"]})
        committed = lessons_index._committed_lesson_files(lessons)
        on_disk = {lessons_index.relative_posix(p, lessons) for p in lessons_index.all_lesson_files(lessons)}
        assert committed == on_disk
        assert lessons_index.removed_lessons(lessons) == []


class TestTheHookTellsTheFailuresApart:
    """The hint is half the defect: `--fix` is the wrong remedy for a hazard."""

    def test_pre_push_branches_on_the_exit_code(self) -> None:
        script = PRE_PUSH.read_text(encoding="utf-8")
        assert "lessons_rc" in script, "the hook still only tests success/failure"
        assert 'if [ "$lessons_rc" -eq 1 ]' in script, "the --fix hint is not gated on exit 1"

    def test_cannot_check_does_not_point_at_a_remedy_nobody_printed(self) -> None:
        """Raised in review on #1714. Exit 2 prints a per-hazard remedy; exit 3
        prints only the reason, so telling that operator to follow "the remedy
        above" sends them looking for text that is not there."""
        script = PRE_PUSH.read_text(encoding="utf-8")
        assert 'elif [ "$lessons_rc" -eq 2 ]' in script, "exit 2 and exit 3 still share one branch"
        assert "could not be checked, and that is not a pass" in script, "exit 3 has no words of its own"

    def test_the_fix_hint_is_not_printed_for_every_failure(self) -> None:
        """Reading the script's shape, because the trap is textual: the hint sat
        unconditionally under the failure branch, so a collision was told to run
        the command that hides it."""
        script = PRE_PUSH.read_text(encoding="utf-8")
        hint = "toolkit tools lessons-index --fix && git commit -a --amend --no-edit"
        assert hint in script, "the hint for the stale-counter case has gone missing"
        before_hint, _, _ = script.partition(hint)
        assert 'if [ "$lessons_rc" -eq 1 ]' in before_hint, (
            "the --fix hint is reachable without the exit-code-1 branch above it"
        )
        assert "Do NOT reach for --fix here" in script, "the hazard branch does not warn against --fix"
