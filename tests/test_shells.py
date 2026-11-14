"""No test starts a bare `"bash"` (#3409): on Windows that is the WSL launcher, see `tests/shells.py`."""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _starts_with_bash(node: ast.AST) -> bool:
    return (
        isinstance(node, (ast.List, ast.Tuple))
        and bool(node.elts)
        and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "bash"
    )


def bare_bash_argvs(source: str) -> list[int]:
    """Line numbers of argv literals that start with the string "bash".

    Any list literal counts, so an argv built first (`cmd = ["bash", ...]`) or
    passed by keyword (`args=[...]`) is caught too. A tuple counts only as a
    call's first argument: `("bash", "jq")` is also how tests name the tools
    they look up with `which`.
    """
    return sorted(
        {
            node.lineno
            for node in ast.walk(ast.parse(source))
            if (isinstance(node, ast.List) and _starts_with_bash(node))
            or (isinstance(node, ast.Call) and node.args and _starts_with_bash(node.args[0]))
        }
    )


def test_the_scan_finds_a_bare_bash_argv_and_passes_a_resolved_one() -> None:
    source = (
        'run(["bash", "-c", "x"])\n'
        'run([BASH, "-c", "x"])\n'
        'any(which(t) for t in ("bash", "jq"))\n'
        'cmd = ["bash", "-c", "x"]\n'
        'run(args=["bash", "x"])\n'
        'run(("bash", "x"))\n'
    )
    assert bare_bash_argvs(source) == [1, 4, 5, 6]


def test_no_test_starts_a_bare_bash() -> None:
    found = [
        f"{path.name}:{line}"
        for path in sorted(TESTS.glob("*.py"))
        for line in bare_bash_argvs(path.read_text(encoding="utf-8"))
    ]
    assert not found, 'use tests.shells.BASH, not a bare "bash" argv (WSL launcher on Windows):\n' + "\n".join(found)
