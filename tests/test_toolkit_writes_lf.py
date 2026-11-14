"""Every file the toolkit writes with `write_text` is LF on every platform (#3480).

`Path.write_text` translates `\\n` to the platform's line separator unless
`newline` is given, so on the operator's Windows workstation (ADR-052) a
generated file came out CRLF and never matched its committed LF copy: a clean
regeneration read as drift. Pinning `newline="\\n"` at each call is the fix,
and this test keeps a new call from forgetting it. The tests are held to it
too: a fixture written CRLF is what the shell scripts under test then read on
Windows (#3409).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOTS = (REPO / "toolkit", REPO / "tests")


def unpinned_write_text_calls(source: str) -> list[int]:
    """Line numbers of `.write_text(...)` calls that pass no `newline` keyword."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write_text"
        and not any(kw.arg == "newline" for kw in node.keywords)
    ]


def test_the_scan_finds_an_unpinned_call_and_passes_a_pinned_one() -> None:
    source = 'p.write_text("a")\np.write_text("a", encoding="utf-8", newline="\\n")\n'
    assert unpinned_write_text_calls(source) == [1]


def test_every_write_text_pins_the_newline() -> None:
    found = [
        f"{path.relative_to(REPO).as_posix()}:{line}"
        for root in ROOTS
        for path in sorted(root.rglob("*.py"))
        for line in unpinned_write_text_calls(path.read_text(encoding="utf-8"))
    ]
    assert not found, 'write_text without newline="\\n" writes CRLF on Windows:\n' + "\n".join(found)
