"""Every text-mode subprocess call states which codec decodes the child's output.

Without `encoding=`, `text=True` decodes with the locale codec: cp1252 on a Windows
workstation, UTF-8 on CI. A child that prints UTF-8 garbles or raises there and passes
here (#2865). The right codec is the child's, so each call decides: `encoding="utf-8"`
for git, gh, kubectl, sops and the like, and an explicit `encoding=None` for a native
Windows tool that really does print in the locale's code page.

The migration runs in slices, so the count of calls that have not decided may only go
down. Lower `UNDECIDED_CEILING` when a slice lands, and delete it at zero.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ROOTS = ("toolkit", "tests")
SPAWNERS = {"run", "Popen", "check_output"}
TEXT_FLAGS = {"text", "universal_newlines"}
UNDECIDED_CEILING = 100


def _undecided(tree: ast.AST) -> list[int]:
    """Lines of text-mode calls to a process spawner that name no `encoding`."""
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if name not in SPAWNERS:
            continue
        keywords = {k.arg: k.value for k in node.keywords}
        text_mode = any(isinstance(keywords.get(f), ast.Constant) and keywords[f].value is True for f in TEXT_FLAGS)
        if text_mode and "encoding" not in keywords:
            lines.append(node.lineno)
    return lines


def _all_undecided() -> list[str]:
    found = []
    for root in ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found += [f"{path.relative_to(REPO)}:{line}" for line in _undecided(tree)]
    return found


@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        ('subprocess.run(["git"], text=True)', 1),
        ('subprocess.Popen(["git"], universal_newlines=True)', 1),
        ('run(["git"], text=True)', 1),
        ('subprocess.run(["git"], text=True, encoding="utf-8")', 0),
        ('subprocess.run(["netsh"], text=True, encoding=None)', 0),
        ('subprocess.run(["git"])', 0),
        ('subprocess.run(["git"], text=False)', 0),
        ('print("x", text=True)', 0),
    ],
)
def test_the_detector_tells_a_decided_call_from_an_undecided_one(source: str, flagged: int) -> None:
    assert len(_undecided(ast.parse(source))) == flagged


def test_undecided_calls_only_ever_go_down() -> None:
    found = _all_undecided()
    assert len(found) <= UNDECIDED_CEILING, (
        f"{len(found)} text-mode subprocess calls name no encoding, ceiling {UNDECIDED_CEILING}. "
        'Add encoding="utf-8", or encoding=None for a tool that prints the locale code page:\n' + "\n".join(found)
    )
