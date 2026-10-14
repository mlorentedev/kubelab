"""TOOL-113 (#2244): a directory bind-mounted into a container lives under $HOME.

On macOS pytest's `tmp_path` sits under `/private/var/folders`, which Colima (like
Docker Desktop) does not share with its VM. The mount then arrives empty, and a
mounted file arrives as a directory, so a test that passes in Linux CI fails on
the Mac for a reason that has nothing to do with what it checks.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def test_the_mount_dir_is_under_home(docker_mount_dir: Path) -> None:
    assert docker_mount_dir.is_dir()
    assert docker_mount_dir.is_relative_to(Path.home()), "Colima and Docker Desktop share $HOME only"


def test_no_test_mounts_pytests_tmp_path_into_a_container() -> None:
    """`docker run -v {tmp_path}:...` is the shape that breaks; use `docker_mount_dir`."""
    pattern = re.compile(r'"-v",\s*f"\{tmp_path')
    offenders = [
        f"{p.name}:{n}"
        for p in TESTS.rglob("test_*.py")
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, offenders
