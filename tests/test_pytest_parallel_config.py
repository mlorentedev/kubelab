"""The suite runs in parallel without dropping a test to make that work (#3078).

`make test` is what CI's required `Tests` check runs, so its command line is
the contract. Two ways to make a parallel run green are wrong and look right:
deselecting the tests that share state, and widening the default marker
expression's exclusions. Instead every test file runs on one worker, in order
(`--dist loadfile`), so a module-scoped fixture sees what a serial run shows it.

Not `loadgroup`: with pytest 9.2 and pytest-xdist 3.8.0 it ignores every
`xdist_group` marker and distributes like `load`, without a word
(pytest-dev/pytest-xdist#1407). So the mode is proved by running it, below.
"""

import re
import shlex
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _make_test_argv() -> list[str]:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = re.search(r"^test:\n\t@?(.+)$", makefile, re.MULTILINE)
    assert recipe, "the Makefile has no `test:` target with a one-line recipe"
    return shlex.split(recipe.group(1))


def _addopts() -> list[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["pytest"]["ini_options"]["addopts"]


def test_make_test_spreads_the_suite_over_every_cpu() -> None:
    argv = _make_test_argv()
    assert "pytest" in argv
    assert argv[argv.index("-n") + 1] == "auto"


def test_the_dist_mode_keeps_a_files_tests_on_one_worker_in_order(tmp_path: Path) -> None:
    """Runs the recipe's own `--dist` value: a flag spelled right is not a mode that works."""
    argv = _make_test_argv()
    dist = argv[argv.index("--dist") + 1]
    log = tmp_path / "ran.log"
    probe = tmp_path / "test_probe.py"
    probe.write_text(
        textwrap.dedent(f"""
            import os
            import pytest

            @pytest.mark.parametrize("case", range(8))
            def test_case(case):
                with open({str(log)!r}, "a", encoding="utf-8") as fh:
                    fh.write(f"{{os.environ['PYTEST_XDIST_WORKER']}} {{case}}\\n")
        """),
        encoding="utf-8",
    )
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", "/dev/null", "-q", "-p", "no:cacheprovider"]
        + ["-n", "2", "--dist", dist, str(probe)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert run.returncode == 0, run.stdout[-500:]
    ran = [line.split() for line in log.read_text(encoding="utf-8").splitlines()]
    assert len({worker for worker, _ in ran}) == 1, f"--dist {dist} split one file over workers: {ran}"
    assert [int(case) for _, case in ran] == list(range(8)), f"--dist {dist} reordered a file: {ran}"


def test_the_parallel_options_stay_out_of_addopts() -> None:
    """Tests that run a nested pytest inherit addopts: `-n` there would fork workers inside workers."""
    assert not any(opt in ("-n", "--numprocesses", "--dist") or opt.startswith("-n") for opt in _addopts())


def test_no_test_is_dropped_to_make_the_parallel_run_pass() -> None:
    opts = _addopts()
    assert opts[opts.index("-m") + 1] == "not e2e and not infra"
    for argv in (opts, _make_test_argv()):
        assert not any(opt.startswith(("--deselect", "--ignore", "-k")) for opt in argv), argv
