"""No live file may reference MinIO once OPS-023 has retired it everywhere (AC5).

Removing a service is where references survive by omission: a Makefile target,
a homepage tile, a test fixture or a runbook step that still names the thing,
and still reads as current. The repository-wide sweep that drives the removal
is only as good as the day it ran, so this test makes the sweep permanent.

"Live" means a file that describes the system as it is. Historical records are
exempt because rewriting them would falsify history: ADRs, lessons, audits,
the changelog and specs (whose own lifecycle archives them). This file is
exempt because it has to name what it forbids.

The removal lands in three PRs, and each must merge green, so the guard is
`xfail(strict=True)` until the last one. `strict` is what keeps it honest: the
moment the sweep is complete the test passes, the xfail becomes a failure, and
removing the marker is forced rather than remembered.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

EXEMPT_PREFIXES = (
    "docs/adr/",
    "docs/lessons/",
    "docs/audits/",
    "specs/",
    "CHANGELOG.md",
    "tests/test_no_live_minio_references.py",
)

PATTERN = re.compile(r"minio", re.IGNORECASE)


def live_minio_references() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode().split("\0")
    offenders = []
    for rel in filter(None, tracked):
        if rel.startswith(EXEMPT_PREFIXES):
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if PATTERN.search(text):
            offenders.append(rel)
    return offenders


def test_the_scan_sees_the_repository() -> None:
    # A scan that reads nothing passes vacuously. Prove it reads real files.
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    assert "Makefile" in tracked
    assert len(tracked) > 500


@pytest.mark.xfail(strict=True, reason="OPS-023: turns green in PR 3, which removes this marker")
def test_no_live_file_references_minio() -> None:
    offenders = live_minio_references()
    assert not offenders, f"{len(offenders)} live file(s) still reference MinIO:\n" + "\n".join(offenders)
