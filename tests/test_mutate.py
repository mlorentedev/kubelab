"""`make mutate` proves a guard goes red without a way to lose the work (TOOL-100, #2104).

The hand-written procedure (commit, mutate, run, `git checkout HEAD -- <file>`)
deleted work whenever the commit had not landed: lesson-480 and its addenda
record it four times, every time by someone who knew the rule. These tests drive
`mutate.run` against a throwaway repository, with the test runner injected.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from toolkit.features import mutate

ORIGINAL = "def guard(x):\n    return x > 0\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "guard.py").write_text(ORIGINAL)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_a_dirty_tree_refuses_before_touching_anything(repo: Path) -> None:
    (repo / "guard.py").write_text(ORIGINAL + "# uncommitted work\n")
    ran: list[str] = []
    with pytest.raises(mutate.Refused, match="not clean"):
        mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", lambda: ran.append("test") or 1)
    assert ran == []
    assert (repo / "guard.py").read_text() == ORIGINAL + "# uncommitted work\n", "the uncommitted work survives"


@pytest.mark.parametrize(("find", "count"), [("x < 0", 0), ("x", 2)])
def test_a_replacement_that_is_not_exactly_one_match_refuses(repo: Path, find: str, count: int) -> None:
    with pytest.raises(mutate.Refused, match=f"matches {count} times"):
        mutate.run(repo, Path("guard.py"), find, "y", lambda: 1)
    assert (repo / "guard.py").read_text() == ORIGINAL


@pytest.mark.parametrize("status", [0, 1, 2, 5])
def test_the_file_is_byte_identical_after_every_run(repo: Path, status: int) -> None:
    seen: list[str] = []

    def run_test() -> int:
        seen.append((repo / "guard.py").read_text())
        return status

    mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test)
    assert seen == [ORIGINAL.replace("x > 0", "x >= 0")], "the test ran against the mutant"
    assert (repo / "guard.py").read_bytes() == ORIGINAL.encode()
    assert _git(repo, "status", "--porcelain") == ""


def test_the_file_is_restored_when_the_test_runner_raises(repo: Path) -> None:
    def run_test() -> int:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test)
    assert (repo / "guard.py").read_bytes() == ORIGINAL.encode()


@pytest.mark.parametrize(
    ("pytest_status", "verdict"),
    [
        (1, mutate.Verdict.RED),  # tests failed: the guard caught the mutant
        (0, mutate.Verdict.GREEN),  # tests passed: the guard missed it
        (2, mutate.Verdict.DID_NOT_RUN),  # collection error, e.g. the mutant is not valid YAML
        (5, mutate.Verdict.DID_NOT_RUN),  # no tests collected
    ],
)
def test_only_a_failing_test_counts_as_red(repo: Path, pytest_status: int, verdict: mutate.Verdict) -> None:
    """A collection error is not the guard going red: a mutation that breaks the
    file's syntax fails every test in it, whether or not they check anything."""
    assert mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", lambda: pytest_status) is verdict


def test_the_exit_codes_tell_the_three_outcomes_apart() -> None:
    assert mutate.Verdict.RED.exit_code == 0
    assert len({v.exit_code for v in mutate.Verdict}) == len(mutate.Verdict)
