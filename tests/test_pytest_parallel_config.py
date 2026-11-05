"""The suite runs in parallel without dropping a test to make that work (#3078).

`make test` is what CI's required `Tests` check runs, so its command line is
the contract. Two ways to make a parallel run green are wrong and look right:
deselecting the tests that share state, and widening the default marker
expression's exclusions. Tests that share state are grouped with
`@pytest.mark.xdist_group` instead, which only `--dist loadgroup` honours.
"""

import re
import shlex
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


def test_make_test_keeps_grouped_tests_on_one_worker() -> None:
    """`load` and `loadfile` ignore `xdist_group`; only `loadgroup` honours it."""
    argv = _make_test_argv()
    assert argv[argv.index("--dist") + 1] == "loadgroup"


def test_the_parallel_options_stay_out_of_addopts() -> None:
    """Tests that run a nested pytest inherit addopts: `-n` there would fork workers inside workers."""
    assert not any(opt in ("-n", "--numprocesses", "--dist") or opt.startswith("-n") for opt in _addopts())


def test_no_test_is_dropped_to_make_the_parallel_run_pass() -> None:
    opts = _addopts()
    assert opts[opts.index("-m") + 1] == "not e2e and not infra"
    for argv in (opts, _make_test_argv()):
        assert not any(opt.startswith(("--deselect", "--ignore", "-k")) for opt in argv), argv
