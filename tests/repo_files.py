"""The files under a repository path that a test reading the source should read.

Listed by git, not walked: a file git ignores is output, and what output a checkout
holds depends on what ran on that machine. `infra/ansible/generated/` held playbooks
an old generator wrote in February, which no playbook reads and a fresh CI clone
never has, and six tests that walked `infra/ansible` failed on them locally while
CI stayed green. Untracked files git does not ignore are listed too, so a file
written for a change is read before it is added.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def repo_files(root: Path, *patterns: str) -> list[Path]:
    """Every file under `root` that git tracks or would add, sorted, with a name matching one of `patterns`.

    A pattern matches the file name, as one passed to `Path.rglob` does; none means every file.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", str(root)],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout.decode()
    paths = (REPO / rel for rel in listed.split("\0") if rel)
    # `is_file`: --cached also lists a tracked file deleted from the working tree.
    return sorted(
        path
        for path in paths
        if path.is_file() and (not patterns or any(fnmatch.fnmatchcase(path.name, p) for p in patterns))
    )
