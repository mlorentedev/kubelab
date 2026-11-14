"""The declared set of tests known to fail on Windows (#3409).

`windows_known_failures.txt` lists them by cause. On Windows, conftest marks
each listed test `xfail` with its section's reason, so the Windows job fails on
a failure outside the list and reports a listed test that passes as XPASS. The
list can therefore only shrink: a new test that breaks on Windows is red, and a
fixed one shows up for removal.

An entry that names a test or file which no longer exists fails
`test_every_entry_names_a_collected_test` on Windows: a renamed test would
otherwise drop out of the list unnoticed and the list would stop describing
anything.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

LIST = Path(__file__).with_name("windows_known_failures.txt")
_SECTION = re.compile(r"^\[(?P<key>[a-z0-9-]+)\]\s+(?P<reason>\S.*)$")


def parse(text: str) -> dict[str, str]:
    """Map each entry to its section's reason. Refuses an entry outside a section, or twice."""
    entries: dict[str, str] = {}
    reason = ""
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        section = _SECTION.match(line)
        if section:
            reason = f"{section['key']}: {section['reason']}"
            continue
        if not reason:
            raise ValueError(f"line {number}: {line!r} comes before any [section] reason")
        if line in entries:
            raise ValueError(f"line {number}: {line!r} is listed twice")
        entries[line] = reason
    return entries


def _matches(entry: str, nodeid: str) -> bool:
    return nodeid == entry if "::" in entry else nodeid.split("::", 1)[0] == entry


def apply(items: list[pytest.Item], entries: dict[str, str]) -> None:
    """Mark every listed item xfail with its entry's reason."""
    for item in items:
        for entry, reason in entries.items():
            if _matches(entry, item.nodeid):
                item.add_marker(pytest.mark.xfail(reason=f"Windows ({reason})", strict=False))
                break


def stale(entries: dict[str, str], nodeids: list[str], root: Path) -> list[str]:
    """The entries that name nothing.

    An entry is judged only when this run could have seen it: its file is missing,
    or its file was collected and no test in it matches. A run of a subset of the
    suite leaves the other files' entries alone.
    """
    ids = set(nodeids)
    collected = {nodeid.split("::", 1)[0] for nodeid in nodeids}
    found = []
    for entry in entries:
        path = entry.split("::", 1)[0]
        if entry in (ids if "::" in entry else collected):
            continue
        if not (root / path).exists() or path in collected:
            found.append(entry)
    return found
