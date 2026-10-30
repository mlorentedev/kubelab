"""`make mutate` proves a guard goes red without a way to lose the work (TOOL-100, #2104).

The hand-written procedure (commit, mutate, run, `git checkout HEAD -- <file>`)
deleted work whenever the commit had not landed: lesson-480 and its addenda
record it four times, every time by someone who knew the rule. These tests drive
`mutate.run` against a throwaway repository, with the test runner injected.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from toolkit.features import mutate

ORIGINAL = "def guard(x):\n    return x > 0\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _statuses(repo: Path, *codes: int) -> tuple[Callable[[], int], list[str]]:
    """A test runner answering `codes` in order, and what `guard.py` held at each call."""
    answers = iter(codes)
    seen: list[str] = []

    def run_test() -> int:
        seen.append((repo / "guard.py").read_text())
        return next(answers)

    return run_test, seen


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
    run_test, seen = _statuses(repo, 0, status)

    mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test)
    assert seen == [ORIGINAL, ORIGINAL.replace("x > 0", "x >= 0")], "the baseline saw the original, then the mutant"
    assert (repo / "guard.py").read_bytes() == ORIGINAL.encode()
    assert _git(repo, "status", "--porcelain") == ""


def test_the_file_is_restored_when_the_test_runner_raises(repo: Path) -> None:
    calls: list[int] = []

    def run_test() -> int:
        calls.append(1)
        if len(calls) == 1:
            return 0  # the baseline
        raise KeyboardInterrupt  # the run against the mutant

    with pytest.raises(KeyboardInterrupt):
        mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test)
    assert len(calls) == 2, "the interrupt hit the mutant's run, not the baseline"
    assert (repo / "guard.py").read_bytes() == ORIGINAL.encode()


@pytest.mark.parametrize(
    ("mutant_status", "verdict"),
    [
        (1, mutate.Verdict.RED),  # tests failed: the guard caught the mutant
        (0, mutate.Verdict.GREEN),  # tests passed: the guard missed it
        (2, mutate.Verdict.DID_NOT_RUN),  # collection error, e.g. the mutant is not valid YAML
        (5, mutate.Verdict.DID_NOT_RUN),  # no tests collected
    ],
)
def test_only_a_failing_test_counts_as_red(repo: Path, mutant_status: int, verdict: mutate.Verdict) -> None:
    """A collection error is not the guard going red: a mutation that breaks the
    file's syntax fails every test in it, whether or not they check anything.
    The baseline passes in every case: only then does the mutant's status mean anything."""
    run_test, seen = _statuses(repo, 0, mutant_status)
    assert mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test) is verdict
    assert seen == [ORIGINAL, ORIGINAL.replace("x > 0", "x >= 0")], "the baseline ran, then the mutant"


def test_a_test_that_does_not_pass_without_the_mutation_refuses(repo: Path) -> None:
    """A red baseline certifies every mutant as RED (measured 2026-10-13: two
    tests failing for an unrelated reason made all mutants of a Terraform-runner
    test read RED, including one the correct baseline showed GREEN)."""
    run_test, seen = _statuses(repo, 1, 1)
    with pytest.raises(mutate.Refused, match=r"does not pass without the mutation \(pytest exit 1\)") as err:
        mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test)
    assert "-k" in str(err.value), "the refusal says how to get a usable baseline"
    assert seen == [ORIGINAL], "the test ran once, against the unmutated file"
    assert (repo / "guard.py").read_bytes() == ORIGINAL.encode()
    assert _git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("baseline", [2, 3, 4])
def test_a_baseline_that_did_not_run_is_not_called_red(repo: Path, baseline: int) -> None:
    """A collection, internal or usage error is no result at all, and `-k` cannot
    fix any of them: the advice for a red baseline would send the operator after
    failures that do not exist."""
    run_test, seen = _statuses(repo, baseline, 1)
    expected = rf"did not run the test to a result without the mutation \(pytest exit {baseline}:"
    with pytest.raises(mutate.Refused, match=expected) as err:
        mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test)
    assert "red baseline" not in str(err.value)
    assert "-k" not in str(err.value)
    assert seen == [ORIGINAL]
    assert (repo / "guard.py").read_bytes() == ORIGINAL.encode()


def test_a_baseline_that_collects_nothing_says_so_and_names_the_marker(repo: Path) -> None:
    """pytest exits 5 when it collects nothing, which is what the repository's
    `-m "not e2e and not infra"` makes of an infra test (#2637). That is not a red
    baseline, and `-k` cannot select a test the marker expression deselected."""
    run_test, seen = _statuses(repo, 5, 1)
    with pytest.raises(mutate.Refused, match=r"collected no test \(pytest exit 5\)") as err:
        mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test)
    assert "red baseline" not in str(err.value)
    assert "-m infra" in str(err.value), "the refusal says how to select a deselected test"
    assert seen == [ORIGINAL]
    assert (repo / "guard.py").read_bytes() == ORIGINAL.encode()


def test_a_marker_in_the_target_selects_a_test_the_default_markers_deselect(tmp_path: Path) -> None:
    """The advice above holds only while a `-m` after the addopts wins over theirs.

    The sample is written here, under the repository's own pytest configuration, so
    the result depends on that configuration and on nothing else in `tests/infra`."""
    root = Path(__file__).resolve().parents[1]
    infra = tmp_path / "test_sample.py"
    infra.write_text("import pytest\n\n\n@pytest.mark.infra\ndef test_live():\n    pass\n")
    argv = [sys.executable, "-m", "pytest", "-c", str(root / "pyproject.toml"), "-q", "--no-cov"]
    argv += ["-p", "no:cacheprovider", "--collect-only", str(infra)]
    deselected = subprocess.run(argv, cwd=root, capture_output=True, text=True)
    selected = subprocess.run([*argv, "-m", "infra"], cwd=root, capture_output=True, text=True)
    assert deselected.returncode == 5, deselected.stdout[-300:]
    assert selected.returncode == 0, selected.stdout[-300:]


def test_a_green_baseline_then_a_red_mutant_is_red_with_two_runs(repo: Path) -> None:
    run_test, seen = _statuses(repo, 0, 1)
    assert mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test) is mutate.Verdict.RED
    assert len(seen) == 2


def test_a_green_baseline_then_a_green_mutant_is_green(repo: Path) -> None:
    run_test, seen = _statuses(repo, 0, 0)
    assert mutate.run(repo, Path("guard.py"), "x > 0", "x >= 0", run_test) is mutate.Verdict.GREEN
    assert seen == [ORIGINAL, ORIGINAL.replace("x > 0", "x >= 0")], "the baseline ran, then the mutant"


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
    recorder = type(
        "Recorder", (), {k: staticmethod(lambda m: said.append(str(m))) for k in ("info", "warning", "error")}
    )
    monkeypatch.setattr(tools, "logger", recorder)
    code = _cli(
        repo, monkeypatch, lambda *a: mutate._PYTEST.get(a[-1](), mutate.Verdict.DID_NOT_RUN), test="does_not_exist.py"
    )
    assert code == mutate.Verdict.DID_NOT_RUN.exit_code
    assert any("not found: does_not_exist.py" in line for line in said), said


def test_the_mutant_never_reaches_the_repository_bytecode_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mutant compiled into the repo's `__pycache__` outlives the restore.

    Python trusts a `.pyc` whose header matches the source's mtime (in whole
    seconds) and size. A same-length mutation restored within the same second
    matches both, so every later run imports the mutant: measured 2026-10-13,
    `0o600` -> `0o644` in the Terraform runner left a test red on correct source.
    The reverse also holds: a cached original read during the mutant's run would
    hide it and report GREEN. The child pytest gets a cache of its own.
    """
    from typer.testing import CliRunner

    from toolkit.cli import tools

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("__pycache__/\n")
    (tmp_path / "limits.py").write_text("MODE = 0o600\n")
    (tmp_path / "test_limits.py").write_text(
        "from limits import MODE\n\n\ndef test_mode():\n    assert MODE == 0o600\n"
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    monkeypatch.setattr(tools.settings, "project_root", tmp_path)

    args = ["mutate", "--file", "limits.py", "--from", "0o600", "--to", "0o644", "--test", "test_limits.py"]
    assert CliRunner().invoke(tools.app, args).exit_code == mutate.Verdict.RED.exit_code
    assert not list(tmp_path.rglob("*.pyc")), "the child compiled into the repository's own bytecode cache"


def test_a_cached_original_cannot_stand_in_for_the_mutant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The false-GREEN direction: the child must compile the mutant, not import a cached original.

    An unchecked-hash `.pyc` (PEP 552) is never validated against its source,
    so it stands in deterministically for the mtime collision of the docstring
    above. Read from the repo's `__pycache__`, it would run the original against
    the test and report GREEN for a mutant the test does catch.
    """
    import py_compile

    from typer.testing import CliRunner

    from toolkit.cli import tools

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("__pycache__/\n")
    (tmp_path / "limits.py").write_text("MODE = 0o600\n")
    (tmp_path / "test_limits.py").write_text(
        "from limits import MODE\n\n\ndef test_mode():\n    assert MODE == 0o600\n"
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    py_compile.compile(str(tmp_path / "limits.py"), invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    monkeypatch.setattr(tools.settings, "project_root", tmp_path)

    args = ["mutate", "--file", "limits.py", "--from", "0o600", "--to", "0o644", "--test", "test_limits.py"]
    assert CliRunner().invoke(tools.app, args).exit_code == mutate.Verdict.RED.exit_code


def test_a_failing_test_target_refuses_through_the_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end with the real pytest: a target already red is refused (exit 2), and the file is untouched."""
    from typer.testing import CliRunner

    from toolkit.cli import tools

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("__pycache__/\n")
    (tmp_path / "limits.py").write_text("MODE = 0o600\n")
    (tmp_path / "test_limits.py").write_text(
        "from limits import MODE\n\n\ndef test_mode():\n    assert MODE == 0o600\n\n\n"
        "def test_unrelated():\n    assert False\n"
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    monkeypatch.setattr(tools.settings, "project_root", tmp_path)

    args = ["mutate", "--file", "limits.py", "--from", "0o600", "--to", "0o644", "--test", "test_limits.py"]
    assert CliRunner().invoke(tools.app, args).exit_code == 2
    assert (tmp_path / "limits.py").read_text() == "MODE = 0o600\n"

    # Deselecting the unrelated failure gives a usable baseline, and the verdict is real.
    deselected = [*args[:-1], "test_limits.py -k test_mode"]
    assert CliRunner().invoke(tools.app, deselected).exit_code == mutate.Verdict.RED.exit_code


def _recipe(*variables: str) -> str:
    """What `make mutate` would run, with TO left out unless given.

    MAKEFLAGS goes too: under an outer make (`make mutate` proving this very test)
    it carries the outer command line, TO= included, into this one.
    """
    outer = {"FROM", "TO", "MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES"}
    env = {k: v for k, v in os.environ.items() if k not in outer}
    repo = Path(__file__).resolve().parent.parent
    args = ["make", "-n", "-C", str(repo), "mutate", "FILE=f.py", "FROM=a", "TEST=t.py", *variables]
    return subprocess.run(args, capture_output=True, text=True, check=True, env=env).stdout


def test_an_empty_replacement_reaches_the_command_as_a_deletion() -> None:
    """`TO=` deletes FROM (#2839). click reads an empty envvar as unset, so make has to pass it as an argument."""
    assert '--to "$TO"' in _recipe("TO=")
    assert '--to "$TO"' in _recipe("TO=x")
    assert "--to" not in _recipe()
    # A TO set in a makefile never reaches the recipe's shell, so `--to "$TO"` would be a deletion.
    assert "--to" not in _recipe("--eval=TO := x")


def test_an_empty_envvar_is_no_replacement_but_an_empty_argument_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Why the recipe passes `--to`: the same empty TO refuses as an envvar and deletes as an argument."""
    from typer.testing import CliRunner

    from toolkit.cli import tools

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("__pycache__/\n")
    (tmp_path / "limits.py").write_text("MODE = 0o600\n")
    (tmp_path / "test_limits.py").write_text(
        "from limits import MODE\n\n\ndef test_mode():\n    assert MODE == 0o600\n"
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    monkeypatch.setattr(tools.settings, "project_root", tmp_path)

    # Deleting the octal prefix leaves `MODE = 600`: still valid Python, and the test goes red.
    args = ["mutate", "--file", "limits.py", "--from", "0o", "--test", "test_limits.py"]
    refused = CliRunner().invoke(tools.app, args, env={"TO": ""})
    assert refused.exit_code == 2
    assert "Missing option '--to'" in refused.output
    assert CliRunner().invoke(tools.app, [*args, "--to", ""]).exit_code == mutate.Verdict.RED.exit_code
    assert (tmp_path / "limits.py").read_text() == "MODE = 0o600\n"
