"""ADR files keep one number each and one status vocabulary (DOCS-026, #1749).

The same ADR number was handed out twice (adr-032), and `status:` drifted into
`active`, a word that says nothing about whether a decision binds. A decision is
`proposed` until it is accepted, and `superseded` once another replaces it.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
VOCABULARY = {"proposed", "accepted", "superseded", "deprecated"}
FRONT_STATUS = re.compile(r"^status:\s*(\S+)\s*$", re.MULTILINE)


def _adrs() -> list[Path]:
    return sorted(ADR_DIR.glob("adr-*.md"))


def test_adr_directory_is_not_empty() -> None:
    assert _adrs(), f"no ADRs found under {ADR_DIR}"


def test_no_adr_number_is_used_twice() -> None:
    numbers = Counter(re.match(r"adr-(\d+)", p.name).group(1) for p in _adrs())  # type: ignore[union-attr]
    assert [n for n, c in numbers.items() if c > 1] == []


def test_front_matter_status_is_in_the_vocabulary() -> None:
    bad: list[str] = []
    for path in _adrs():
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        front = text.split("---", 2)[1]
        match = FRONT_STATUS.search(front)
        if match and match.group(1).strip("\"'").lower() not in VOCABULARY:
            bad.append(f"{path.name}: {match.group(1)}")
    assert bad == [], f"status must be one of {sorted(VOCABULARY)}: {bad}"
