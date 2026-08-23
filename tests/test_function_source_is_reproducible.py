"""A deployed artefact must be a function of git, not of somebody's disk.

`archive_file` zips a DIRECTORY as it exists on the filesystem. It does not read
.gitignore, so a file that is invisible in review — precisely because it is
gitignored — still ships. That is how `__pycache__/main.cpython-312.pyc` ended up
inside the billing kill switch's deployment package.

The damage was not the stray file. A `.pyc` embeds the source file's mtime and
size in its header, so a checkout, a fresh clone or a local test run changed the
zip's bytes with no line of code changing. `terraform plan` then reported
`detect_md5hash -> "different hash"` on every run, and the `gcp-bootstrap` root
never converged — while the compute root did.

**A plan that always shows a change cannot detect drift, which is the only thing
a plan is for.** Worse, it hides drift: had the deployed function been edited by
hand, the plan would have looked identical to this noise. The kill switch is the
mechanism that stops the project billing beyond its budget, so "we cannot tell
whether the deployed code matches the repo" is not a cosmetic state.

Two properties are asserted, and the second is the general one:

1. The excludes exist and cover Python bytecode.
2. Nothing untracked-but-present sits in a packaged source directory. That is the
   property that survives the next language: it does not mention `.pyc` at all,
   it says the artefact is determined by what is committed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
KILLSWITCH_TF = REPO / "infra/terraform/gcp-bootstrap/killswitch.tf"


def _archive_file_blocks(tf: str) -> list[tuple[str, str]]:
    """Every `data "archive_file" "<name>" { ... }` block as (name, body)."""
    blocks = []
    for match in re.finditer(r'data\s+"archive_file"\s+"([^"]+)"\s*\{', tf):
        start = match.end()
        depth = 1
        i = start
        while i < len(tf) and depth:
            if tf[i] == "{":
                depth += 1
            elif tf[i] == "}":
                depth -= 1
            i += 1
        blocks.append((match.group(1), tf[start : i - 1]))
    return blocks


def _source_dirs(tf: str) -> list[Path]:
    """Resolve each block's `source_dir` to a real path."""
    dirs = []
    for _name, body in _archive_file_blocks(tf):
        m = re.search(r'source_dir\s*=\s*"\$\{path\.module\}/([^"]+)"', body)
        if m:
            dirs.append(KILLSWITCH_TF.parent / m.group(1))
    return dirs


class TestArchiveExcludes:
    def test_every_archive_file_excludes_python_bytecode(self) -> None:
        tf = KILLSWITCH_TF.read_text()
        blocks = _archive_file_blocks(tf)
        assert blocks, "no archive_file block found; this test is watching nothing"
        for name, body in blocks:
            assert "excludes" in body, (
                f'archive_file "{name}" declares no excludes. It zips the directory as it '
                "exists on disk and does NOT consult .gitignore, so gitignored build output "
                "ships with the function and makes the zip's bytes depend on local state."
            )
            assert "__pycache__" in body, (
                f'archive_file "{name}" does not exclude __pycache__. A .pyc embeds the '
                "source file's mtime, so the zip changes whenever anything touches the "
                "source -- and terraform plan then reports a change forever."
            )


class TestTheArtefactIsDeterminedByGit:
    """The general property, stated without naming a language or a file type."""

    def test_no_untracked_files_in_a_packaged_source_directory(self) -> None:
        dirs = _source_dirs(KILLSWITCH_TF.read_text())
        assert dirs, "no source_dir resolved; this test is watching nothing"

        for source_dir in dirs:
            assert source_dir.is_dir(), f"{source_dir} does not exist"
            # --others: untracked. --exclude-standard: honour .gitignore, which is
            # exactly the set archive_file would ship and review would never see.
            result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "--ignored", "--", str(source_dir)],
                cwd=REPO,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, f"git ls-files failed: {result.stderr}"
            stray = [line for line in result.stdout.splitlines() if line.strip()]
            if not stray:
                continue

            tf = KILLSWITCH_TF.read_text()
            unexcluded = [s for s in stray if "__pycache__" not in s and not s.endswith(".pyc")]
            assert not unexcluded, (
                f"{source_dir.relative_to(REPO)} contains gitignored files that archive_file "
                f"would package and no exclude covers: {unexcluded}. The deployed artefact "
                "must be a function of what is committed, not of what happens to be on this "
                "machine -- otherwise two people deploying the same commit ship different "
                "bytes, and terraform plan can no longer tell drift from noise."
            )
            # The known ones are present on this machine and excluded by config;
            # asserting they ARE excluded is what makes the exclude list honest.
            assert "excludes" in tf and "__pycache__" in tf


@pytest.mark.parametrize("needle", ["*.pyc", "__pycache__"])
def test_exclude_list_covers_both_shapes(needle: str) -> None:
    # Both forms matter: `__pycache__/**` misses a stray .pyc beside the source,
    # and `*.pyc` alone leaves the directory entry itself in the archive.
    assert needle in KILLSWITCH_TF.read_text()
