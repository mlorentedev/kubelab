"""Every `toolkit <group> <command>` an instruction tells you to run must exist.

The `make` half of this check is `tests/test_runbook_targets_exist.py`; this is the
toolkit half, and it reads the same documents for the same reason. A removed
command group fails with `No such command`, which reads as a broken install rather
than as a broken instruction. `toolkit apps` was removed and stayed in ten
troubleshooting commands until #836 found it by reading.

Scope is existence of the command path, not its options or arguments: the CLI is
walked group by group until the documented words reach a leaf command.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import typer

from tests.test_runbook_targets_exist import _FENCE, _INLINE, REPO, _runbooks
from toolkit.main import app

# `toolkit` in command position: at the start of a line (after an optional `$ `
# prompt), behind `poetry run`, or after a shell separator, each optionally
# followed by `VAR=value` assignments or `sudo`/`exec`/`time`. Words are read on the
# same line only. Prose in a code comment ("the toolkit mints ...") is not a call,
# and a word on the next line is not an argument. Not `tk`: that alias is the
# operator's shell function, not something the repository installs.
_TOOLKIT_CALL = re.compile(
    r"(?m)(?:^[ \t]*(?:\$[ \t]+)?|poetry[ \t]+run[ \t]+|&&[ \t]*|;[ \t]*|\|[ \t]*|\$\()"
    r"(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S*|sudo|exec|time)[ \t]+)*"
    r"toolkit((?:[ \t]+[a-z][a-z0-9-]*)+)"
)


def _root() -> Any:
    # Typer vendors its own click, so the group is recognised by its `commands`
    # mapping rather than by `isinstance` against the installed click.
    command = typer.main.get_command(app)
    assert hasattr(command, "commands"), type(command)
    return command


def _missing(words: list[str], group: Any) -> str | None:
    """The first word that names no subcommand, or None when the path resolves."""
    current = group
    for word in words:
        if not hasattr(current, "commands"):
            return None  # reached a leaf: what follows is its arguments
        child = current.commands.get(word)
        if child is None:
            return word
        current = child
    return None


def _calls(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    code = [m.group(0) for m in _FENCE.finditer(text)]
    code += [m.group(1) for m in _INLINE.finditer(_FENCE.sub("", text))]
    return [m.group(1).strip() for chunk in code for m in _TOOLKIT_CALL.finditer(chunk)]


# Calls that stay, each with its reason. Keyed by (document, call) like the make
# ledger, so an entry excuses one document's text and nothing else.
KNOWN_STALE: dict[tuple[str, str], str] = {
    # -- Not instructions: each names a command that a sentence says does not exist yet.
    ("docs/runbooks/break-glass.md", "auth drill-idp-down"): "named as the next AC7 step, not run",
    ("docs/runbooks/dns-homelab.md", "infra homelab"): "named as a subcommand to consider, not run",
    (
        "docs/runbooks/onboard-vpn-fleet-agent.md",
        "infra headscale mint-agent-key",
    ): "named as VPN-ACL-007's future wrapper",
    # -- Components no dev stack runs any more: these sections need rewriting, not a rename (#836).
    (
        "docs/troubleshooting/networking-dns.md",
        "edge restart dns-gateway",
    ): "dns-gateway has no stack; section to rewrite",
    ("docs/troubleshooting/networking-dns.md", "edge restart nginx"): "nginx has no stack; section to rewrite",
    ("docs/troubleshooting/services-traefik-nginx.md", "edge restart nginx"): "nginx has no stack; section to rewrite",
}


def _broken() -> set[tuple[str, str]]:
    root = _root()
    return {
        (doc.relative_to(REPO).as_posix(), call)
        for doc in _runbooks()
        for call in _calls(doc)
        if _missing(call.split(), root) is not None
    }


@pytest.mark.parametrize(
    ("line", "call"),
    [
        ("toolkit services logs api", "services logs api"),
        ("$ poetry run toolkit config get x", "config get x"),
        ("ENV=dev toolkit apps logs api", "apps logs api"),
        ("A=1 B=2 toolkit apps up", "apps up"),
        ("sudo toolkit edge restart traefik", "edge restart traefik"),
        ("make x && toolkit apps down", "apps down"),
        ("# the toolkit mints a key", None),
        ("see toolkit apps in the old docs", None),
    ],
)
def test_the_scan_finds_toolkit_in_command_position_only(line: str, call: str | None) -> None:
    found = [m.group(1).strip() for m in _TOOLKIT_CALL.finditer(line)]
    assert found == ([call] if call else []), found


def test_the_scan_reaches_documented_toolkit_commands() -> None:
    """A regex that matched nothing would pass every document."""
    found = [call for doc in _runbooks() for call in _calls(doc)]
    assert len(found) > 20, found


def test_every_documented_toolkit_command_exists() -> None:
    broken = sorted(_broken() - KNOWN_STALE.keys())
    assert not broken, "documented toolkit commands that do not exist:\n" + "\n".join(
        f"{doc}: toolkit {call}" for doc, call in broken
    )


def test_the_ledger_only_shrinks() -> None:
    """An entry whose call is gone, or now resolves, must leave the ledger."""
    stale = sorted(KNOWN_STALE.keys() - _broken())
    assert not stale, f"no longer broken, remove from KNOWN_STALE: {stale}"
