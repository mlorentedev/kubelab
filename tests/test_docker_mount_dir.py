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
    """`docker run -v {tmp_path}:...` is the shape that breaks; use `docker_mount_dir`.

    Read over each file's whole text, so a `-v` and its value on separate lines
    still count, and over every module under tests/, helpers included.
    """
    pattern = re.compile(r'(?:"-v",\s*(?:f"\{|str\()|f"-v\s*\{)tmp_path')
    offenders = [
        f"{p.relative_to(TESTS)}:{text.count(chr(10), 0, m.start()) + 1}"
        for p in TESTS.rglob("*.py")
        if p != Path(__file__).resolve()
        for text in [p.read_text(encoding="utf-8")]
        for m in pattern.finditer(text)
    ]
    assert not offenders, offenders
