"""The dev node token's acceptance probe names a missing fixture instead of blaming the token (#2750).

The probe is the check after every rotation of the dev node's token
(docs/runbooks/dev-node-token-rotation.md). On 2026-10-28 its fixture repository
was gone, and the probe wrote the generic F2_FAIL, which reads as a broken
credential. A 404 now has its own verdict; every other lookup failure stays F2_FAIL.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "specs/archive/ANSIBLE-033-dev-node-credentials/probes/f2-private-repo-flow.sh"

# `gh api` writes its error to stderr and exits 1, whatever the status.
GH_STUB = """#!/bin/sh
echo "$GH_STDERR" >&2
exit 1
"""


def _verdict(tmp_path: Path, gh_stderr: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB, encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    result = tmp_path / "result"
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "GH_STDERR": gh_stderr,
        "F2_RESULT": str(result),
        "F2_WORK": str(tmp_path / "work"),
    }
    subprocess.run(["bash", str(PROBE)], env=env, capture_output=True, text=True, timeout=30, check=False)
    return result.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize(
    ("gh_stderr", "verdict"),
    [
        ("gh: Not Found (HTTP 404)", "F2_FIXTURE_UNREACHABLE"),
        ("gh: Bad credentials (HTTP 401)", "F2_FAIL"),
        ("error connecting to api.github.com", "F2_FAIL"),
    ],
)
def test_a_failed_fixture_lookup_is_named_by_its_cause(tmp_path: Path, gh_stderr: str, verdict: str) -> None:
    assert _verdict(tmp_path, gh_stderr) == verdict


def test_the_runbook_names_every_verdict_the_probe_writes() -> None:
    """The runbook is where an operator reads a verdict; one it does not name sends them guessing."""
    runbook = (REPO / "docs/runbooks/dev-node-token-rotation.md").read_text(encoding="utf-8")
    probe = PROBE.read_text(encoding="utf-8")
    written = {v for v in ("F2_OK", "F2_FAIL", "F2_FIXTURE_ARCHIVED", "F2_FIXTURE_UNREACHABLE") if f'"{v}"' in probe}
    assert "F2_FIXTURE_UNREACHABLE" in written
    assert not {v for v in written if v not in runbook}, written
