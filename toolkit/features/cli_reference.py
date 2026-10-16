"""Render the toolkit's command tree as Markdown, and splice it into its README.

`toolkit/README.md` documented a layout and a set of command groups the package
never had (#1751). A hand-written command list drifts the moment a command is
added, so the list is derived from the live Typer tree and a test compares the
committed block with a fresh render.
"""

from __future__ import annotations

from typing import Any

import click
import typer

START = "<!-- cli-reference:start -->"
END = "<!-- cli-reference:end -->"


def _summary(cmd: Any) -> str:
    """First sentence of a command's help, on one line, safe inside a table cell."""
    text = (getattr(cmd, "short_help", None) or getattr(cmd, "help", None) or "").strip()
    first = " ".join(text.split("\n\n")[0].split())
    return first.replace("|", "\\|")


def _walk(cmd: Any, path: tuple[str, ...]) -> list[tuple[tuple[str, ...], str]]:
    """Every command below `cmd`, depth first, sorted by name so a render is stable."""
    rows: list[tuple[tuple[str, ...], str]] = []
    for name, sub in sorted(getattr(cmd, "commands", {}).items()):
        rows.append(((*path, name), _summary(sub)))
        rows.extend(_walk(sub, (*path, name)))
    return rows


def render(app: typer.Typer) -> str:
    """One table of `toolkit <path>` against its one-line help, groups first."""
    root = typer.main.get_command(app)
    lines = ["| Command | What it does |", "|---|---|"]
    for path, summary in _walk(root, ()):
        lines.append(f"| `toolkit {' '.join(path)}` | {summary} |")
    return "\n".join(lines)


def splice(readme: str, block: str) -> str:
    """Replace what sits between the markers; the markers themselves must exist once."""
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise click.UsageError(f"the README must contain {START} and {END} exactly once")
    head, rest = readme.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n\n{block}\n\n{END}{tail}"
