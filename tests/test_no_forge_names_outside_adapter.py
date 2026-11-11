"""No module but the forge adapter compares a `forge` with a forge name (IDP-053 AC8).

A string compare on `entry.forge` is how the receiver, `product ready` and `product
release-contract` each came to refuse every forge but GitHub, and how a second forge would
have meant editing all three. The factory in `forge_adapter.py` is the one place that knows
which forges exist, so a new forge is one implementation and one registry line.

The scan reads the syntax tree, not the text: a comment or an error message that says
"github" is not a compare, and `forge in ("github", "gitea")` is one a grep would miss.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLKIT = REPO_ROOT / "toolkit"
ADAPTER = TOOLKIT / "features" / "forge_adapter.py"

#: What a forge is called in `products.yaml`. `in-tree` is the absence of a forge, not one.
FORGE_NAMES = frozenset({"github", "gitea"})

#: Modules allowed to name a forge, each with the slice that removes it.
ALLOWED = {
    # IDP-053 S9 moves `_provenance` behind the adapter and deletes this entry. Until then the
    # judge keeps its own `forge == "github"` branch: no earlier slice touches deploy_shape.py.
    TOOLKIT / "features" / "deploy_shape.py",
}


def _is_forge_operand(node: ast.expr) -> bool:
    name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
    return name == "forge" or name.endswith("_forge")


def _names_a_forge(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value in FORGE_NAMES
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return any(_names_a_forge(item) for item in node.elts)
    return False


def forge_compares(source: str) -> list[int]:
    """Line numbers of every comparison between a `forge` value and a forge name."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if any(_is_forge_operand(o) for o in operands) and any(_names_a_forge(o) for o in operands):
            lines.append(node.lineno)
    return lines


def _modules() -> list[pathlib.Path]:
    return sorted(p for p in TOOLKIT.rglob("*.py") if p != ADAPTER)


@pytest.mark.parametrize(
    "source",
    [
        'entry.forge != "github"',
        'forge == "gitea"',
        '"github" == product.forge',
        'entry.forge in ("github", "gitea")',
        'product.forge not in {"github"}',
        'self.source_forge == "gitea"',
    ],
)
def test_the_scan_sees_each_way_a_forge_is_compared_to_a_name(source: str) -> None:
    assert forge_compares(source) == [1]


@pytest.mark.parametrize(
    "source",
    [
        'entry.forge == "in-tree"',
        'service == "github"',
        'print("the forge is github")',
        'forge = "github"',
        "entry.forge != other.forge",
    ],
)
def test_the_scan_leaves_alone_what_is_not_a_forge_name_compare(source: str) -> None:
    assert forge_compares(source) == []


def test_no_module_outside_the_adapter_compares_a_forge_with_a_forge_name() -> None:
    offenders = {
        f"{path.relative_to(REPO_ROOT)}:{line}"
        for path in _modules()
        if path not in ALLOWED
        for line in forge_compares(path.read_text(encoding="utf-8"))
    }

    assert not offenders, (
        f"{sorted(offenders)} compare a forge with a name. Ask `adapter_for(app, entry)` in "
        "toolkit/features/forge_adapter.py instead: it refuses a forge with no implementation."
    )


@pytest.mark.parametrize("path", sorted(ALLOWED, key=str), ids=lambda p: p.name)
def test_an_allow_listed_module_still_needs_its_entry(path: pathlib.Path) -> None:
    """An entry that matches nothing is a hole left open for the next module that is named there."""
    assert forge_compares(path.read_text(encoding="utf-8")), f"{path.name} no longer names a forge: drop its entry"
