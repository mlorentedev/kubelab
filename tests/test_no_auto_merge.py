"""Nothing in this repository enables auto-merge (TOOL-021 AC11).

Auto-merge lands a pull request the instant its checks go green, which bypasses
the human merge the review-attestation gate exists to inform: the gate makes an
unreviewed PR visible, and a person still decides. The spec asked for this to be
asserted by a test rather than by inspection, because inspection is what a
one-line `--auto` in a workflow slips past.

The scan covers every file that can act on the forge -- workflows, composite
actions, the Makefile, the toolkit, scripts and the harness. Whole-line
comments are skipped: several workflows explain in a comment why
`allow_auto_merge` stays false, and that sentence must not trip the guard. A
trailing comment on a code line is NOT stripped, on purpose: `#` also appears
inside strings and URLs, and cutting there could hide a real `--auto`. The cost
is a spurious red on a line like `gh pr merge --squash  # no --auto`, which fails
closed and is fixed by moving the remark onto its own line.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Each pattern is one way to switch auto-merge on: the CLI flag, the GraphQL
# mutation, the REST/settings field set true, or a marketplace action whose only
# job is to merge.
ENABLERS: dict[str, re.Pattern[str]] = {
    "gh pr merge --auto": re.compile(r"\bgh\s+pr\s+merge\b[^\n]*--auto\b"),
    "enablePullRequestAutoMerge": re.compile(r"enablePullRequestAutoMerge"),
    "allow_auto_merge true": re.compile(r"""["']?allow_auto_merge["']?\s*[:=]\s*["']?true\b""", re.IGNORECASE),
    "automerge action": re.compile(r"uses:\s*\S*(automerge|auto-merge)\S*", re.IGNORECASE),
}

# Surfaces that exist today: each must match at least one file, or the guard
# would pass over an empty sample after a rename or a move.
REQUIRED_GLOBS = (
    ".github/workflows/*.yml",
    "Makefile",
    "toolkit/**/*.py",
    "scripts/**/*",
    "harness/**/*.json",
)
# Surfaces scanned when present. The repository has no composite actions yet.
OPTIONAL_GLOBS = (
    ".github/workflows/*.yaml",
    ".github/actions/**/*.yml",
    ".github/actions/**/*.yaml",
)
SCANNED_GLOBS = REQUIRED_GLOBS + OPTIONAL_GLOBS


def _comment_free(line: str) -> str:
    """The line, or nothing when the whole line is a `#` comment (YAML, Make, shell, Python)."""
    return "" if line.lstrip().startswith("#") else line


def _scanned_files() -> list[Path]:
    files = {p for pattern in SCANNED_GLOBS for p in ROOT.glob(pattern) if p.is_file()}
    return sorted(files)


def find_enablers(text: str) -> list[str]:
    """Names of the auto-merge enablers present in the code lines of `text`."""
    code = "\n".join(_comment_free(line) for line in text.splitlines())
    return [name for name, pattern in ENABLERS.items() if pattern.search(code)]


@pytest.mark.parametrize("pattern", REQUIRED_GLOBS)
def test_every_required_surface_is_reached(pattern: str) -> None:
    """A glob that matched nothing would make the guard below pass vacuously for it."""
    assert any(p.is_file() for p in ROOT.glob(pattern)), f"{pattern} matched no file"


def test_nothing_enables_auto_merge() -> None:
    hits = {
        str(path.relative_to(ROOT)): found
        for path in _scanned_files()
        if (found := find_enablers(path.read_text(encoding="utf-8", errors="replace")))
    }
    assert hits == {}, f"auto-merge enabled in: {hits}"


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ('      - run: gh pr merge "$PR" --squash --auto', ["gh pr merge --auto"]),
        (
            "mutation { enablePullRequestAutoMerge(input: {pullRequestId: $id}) { clientMutationId } }",
            ["enablePullRequestAutoMerge"],
        ),
        ('{"allow_auto_merge": true}', ["allow_auto_merge true"]),
        ("      - uses: pascalgn/automerge-action@v0.16.4", ["automerge action"]),
        ("  # `allow_auto_merge` stays false; a person merges.", []),
        ('      - run: gh pr merge "$PR" --squash', []),
    ],
    ids=["cli-flag", "graphql", "setting", "action", "comment", "plain-merge"],
)
def test_each_enabler_is_recognised(snippet: str, expected: list[str]) -> None:
    """The patterns catch what they name, and a deliberate human merge is not one."""
    assert find_enablers(snippet) == expected
