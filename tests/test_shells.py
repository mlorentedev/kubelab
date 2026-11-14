"""No test starts a bare `"bash"` (#3409): on Windows that is the WSL launcher, see `tests/shells.py`."""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def bare_bash_argvs(source: str) -> list[int]:
    """Line numbers of calls whose first argument is an argv literal starting with the string "bash"."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and node.args
        and isinstance(node.args[0], (ast.List, ast.Tuple))
        and node.args[0].elts
        and isinstance(node.args[0].elts[0], ast.Constant)
        and node.args[0].elts[0].value == "bash"
    ]


def test_the_scan_finds_a_bare_bash_argv_and_passes_a_resolved_one() -> None:
    source = 'run(["bash", "-c", "x"])\nrun([BASH, "-c", "x"])\nany(which(t) for t in ("bash", "jq"))\n'
    assert bare_bash_argvs(source) == [1]


def test_no_test_starts_a_bare_bash() -> None:
    found = [
        f"{path.name}:{line}"
        for path in sorted(TESTS.glob("*.py"))
        for line in bare_bash_argvs(path.read_text(encoding="utf-8"))
    ]
    assert not found, 'use tests.shells.BASH, not a bare "bash" argv (WSL launcher on Windows):\n' + "\n".join(found)
