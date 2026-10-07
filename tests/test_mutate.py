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
    """The contract the Makefile documents; 2 is the refusal, outside the enum."""
    assert {v: v.exit_code for v in mutate.Verdict} == {
        mutate.Verdict.RED: 0,
        mutate.Verdict.GREEN: 1,
        mutate.Verdict.DID_NOT_RUN: 3,
    }


def test_a_file_that_cannot_be_read_refuses(repo: Path) -> None:
    with pytest.raises(mutate.Refused):
        mutate.run(repo, Path("missing.py"), "a", "b", lambda: 0)
    (repo / "blob.bin").write_bytes(b"\xff\xfe")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "blob")
    with pytest.raises(mutate.Refused):
        mutate.run(repo, Path("blob.bin"), "a", "b", lambda: 0)


def _cli(repo: Path, monkeypatch: pytest.MonkeyPatch, run, test: str = "t.py") -> int:
    from typer.testing import CliRunner

    from toolkit.cli import tools

    monkeypatch.setattr(tools.settings, "project_root", repo)
    monkeypatch.setattr(mutate, "run", run)
    args = ["mutate", "--file", "guard.py", "--from", "x > 0", "--to", "x >= 0", "--test", test]
    return CliRunner().invoke(tools.app, args).exit_code


@pytest.mark.parametrize("verdict", list(mutate.Verdict))
def test_the_command_exits_with_the_verdict_it_reached(
    repo: Path, monkeypatch: pytest.MonkeyPatch, verdict: mutate.Verdict
) -> None:
    assert _cli(repo, monkeypatch, lambda *_: verdict) == verdict.exit_code


def test_a_refusal_exits_2(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_):
        raise mutate.Refused("dirty")

    assert _cli(repo, monkeypatch, refuse) == 2


@pytest.mark.parametrize("stop", [RuntimeError("the test wrote something"), KeyboardInterrupt()])
def test_a_crash_or_an_interrupt_is_no_verdict_never_green(
    repo: Path, monkeypatch: pytest.MonkeyPatch, stop: BaseException
) -> None:
    """Python's exit for an uncaught exception, and Click's for Ctrl-C, are both GREEN's 1."""

    def crash(*_):
        raise stop

    assert _cli(repo, monkeypatch, crash) == mutate.Verdict.DID_NOT_RUN.exit_code


@pytest.mark.parametrize("test", ["", "   "])
def test_an_empty_test_target_refuses_before_mutating(repo: Path, monkeypatch: pytest.MonkeyPatch, test: str) -> None:
    """An empty target runs the whole suite, and the whole suite goes red against nearly anything."""
    ran = []
    assert _cli(repo, monkeypatch, lambda *a: ran.append(a), test=test) == 2
    assert not ran


def test_why_pytest_ran_nothing_reaches_the_operator(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A mistyped TEST is NO VERDICT; the cause is on pytest's stderr, not its stdout."""
    from toolkit.cli import tools

    said: list[str] = []
    recorder = type("Recorder", (), {k: staticmethod(lambda m: said.append(str(m))) for k in ("info", "warning", "error")})
    monkeypatch.setattr(tools, "logger", recorder)
    code = _cli(repo, monkeypatch, lambda *a: mutate._PYTEST.get(a[-1](), mutate.Verdict.DID_NOT_RUN), test="does_not_exist.py")
    assert code == mutate.Verdict.DID_NOT_RUN.exit_code
    assert any("not found: does_not_exist.py" in line for line in said), said
