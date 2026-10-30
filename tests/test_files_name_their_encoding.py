"""Every text file the toolkit and its tests read or write names its encoding.

Without one, Python uses the locale codec: cp1252 on a Windows workstation, UTF-8
on CI. The repository's sources hold UTF-8 (em dashes, arrows, accented names), so
an implicit read is a crash or silent mojibake on Windows and nothing at all on
Linux, which is why CI never caught it (lesson-289, lesson-666). ruff's PLW1514
misses a `read_text()` on anything it cannot type as a Path, such as an attribute,
so this walks the syntax tree itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOTS = ("toolkit", "tests")
TEXT_METHODS = {"read_text", "write_text"}
# Openers whose default mode is binary: text only when the mode says `t`.
BINARY_DEFAULT_MODULES = {"gzip", "bz2", "lzma"}
# `os.open` returns a descriptor and archive openers return bytes: no encoding to name.
NOT_TEXT_MODULES = {"os", "tarfile", "zipfile"}
TEMPFILE_OPENERS = {"NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"}


def _mode(call: ast.Call, position: int) -> ast.expr | None:
    if len(call.args) > position:
        return call.args[position]
    return next((k.value for k in call.keywords if k.arg == "mode"), None)


def _text_mode(call: ast.Call, position: int = 1, binary_default: bool = False) -> bool:
    """`open(path)` and `open(path, "r")` are text; a mode with `b` is not.

    With `binary_default`, an absent mode means bytes (`tempfile`'s `w+b`).
    """
    mode = _mode(call, position)
    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
        return mode is not None or not binary_default
    return "b" not in mode.value


def _opens_text(func: ast.expr, call: ast.Call) -> bool:
    if isinstance(func, ast.Name):
        if func.id == "open":
            return _text_mode(call)
        return func.id in TEMPFILE_OPENERS and _text_mode(call, 0, binary_default=True)
    if not isinstance(func, ast.Attribute):
        return False
    owner = func.value.id if isinstance(func.value, ast.Name) else None
    if func.attr == "fdopen":
        return _text_mode(call)
    if func.attr in TEMPFILE_OPENERS:
        return _text_mode(call, 0, binary_default=True)
    if func.attr != "open" or owner in NOT_TEXT_MODULES:
        return False
    if owner in BINARY_DEFAULT_MODULES:  # gzip/bz2/lzma read and write bytes unless the mode says `t`
        mode = _mode(call, 1)
        return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "t" in mode.value
    if owner == "io":
        return _text_mode(call)
    return _text_mode(call, 0)  # `Path.open(mode)`: the mode is the first argument


def unspecified_encodings(roots: tuple[str, ...] = ROOTS, repo: Path = REPO) -> list[str]:
    """`path:line` of each text read or write that names no encoding."""
    found = []
    for root in roots:
        for path in sorted((repo / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            lines = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or any(k.arg == "encoding" for k in node.keywords):
                    continue
                func = node.func
                method = isinstance(func, ast.Attribute) and func.attr in TEXT_METHODS
                if method or _opens_text(func, node):
                    lines.add(node.lineno)
            found += [f"{path.relative_to(repo).as_posix()}:{line}" for line in sorted(lines)]
    return found


def test_every_text_read_and_write_names_its_encoding() -> None:
    found = unspecified_encodings()
    assert not found, 'add encoding="utf-8" to:\n  ' + "\n  ".join(found)


def test_the_scan_sees_each_form_it_must_refuse(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text(
        "from pathlib import Path\n"
        "class C:\n"
        "    F = Path('x')\n"
        "    def a(self):\n"
        "        return self.F.read_text()\n"  # an attribute: the form PLW1514 misses
        "def b(p, fd):\n"
        "    p.write_text('x')\n"
        "    open(p)\n"
        "    open(p, 'r')\n"
        "    p.open('w')\n"
        "    os.fdopen(fd, 'w')\n"
        "    gzip.open(p, 'wt')\n"
        "    tempfile.NamedTemporaryFile('w')\n"
        "def ok(p, fd):\n"
        "    p.read_text(encoding='utf-8')\n"
        "    open(p, 'rb')\n"
        "    open(p, mode='wb')\n"
        "    p.read_bytes()\n"
        "    p.open('rb')\n"
        "    p.open('w', encoding='utf-8')\n"
        "    os.open(p, 0)\n"
        "    os.fdopen(fd, 'wb')\n"
        "    gzip.open(p)\n"
        "    tarfile.open(p, 'w:gz')\n"
        "    tempfile.NamedTemporaryFile()\n",
        encoding="utf-8",
    )

    assert unspecified_encodings(("pkg",), tmp_path) == [f"pkg/m.py:{n}" for n in (5, 7, 8, 9, 10, 11, 12, 13)]
