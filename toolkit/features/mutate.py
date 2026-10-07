"""Prove a guard goes red against one mutation, without a way to lose work (TOOL-100, #2104).

The procedure this replaces was a shell line: commit, mutate, run the test,
`git checkout HEAD -- <file>`. Its safety rested on the commit having landed, and
a commit a pre-commit hook refuses leaves HEAD where it was, so the restore then
reset the file to an older version (lesson-480, four recurrences). Here the
restore does not depend on HEAD at all: the file's own bytes are kept in memory
and written back, and a dirty tree is refused before anything is touched.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from enum import Enum
from pathlib import Path


class Refused(Exception):
    """Nothing was mutated: the preconditions do not hold."""


class Verdict(Enum):
    """What the mutation run showed, with the exit code `make mutate` returns."""

    RED = 0  # the test failed against the mutant: the guard catches it
    GREEN = 1  # the test passed against the mutant: the guard misses it
    DID_NOT_RUN = 3  # pytest errored or collected nothing: no verdict either way

    @property
    def exit_code(self) -> int:
        return self.value


#: pytest's exit codes: 0 all passed, 1 some failed; anything else means the
#: tests did not run to a verdict (2 interrupted or a collection error, 3
#: internal error, 4 usage error, 5 nothing collected).
_PYTEST = {0: Verdict.GREEN, 1: Verdict.RED}


def _dirty(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def run(repo: Path, file: Path, find: str, replace: str, run_test: Callable[[], int]) -> Verdict:
    """Replace the one occurrence of `find` in `file`, run the test, put the file back.

    Refuses on a dirty tree: the clean tree is what makes "put it back" the same
    as "as it was committed", and what keeps uncommitted work out of reach. The
    file is restored from the bytes read here, in a `finally`, so an interrupted
    test restores it too.
    """
    if dirty := _dirty(repo):
        raise Refused(f"the working tree is not clean; commit first:\n{dirty}")

    path = repo / file
    try:
        original = path.read_bytes()
        text = original.decode()
    except (OSError, UnicodeDecodeError) as exc:
        raise Refused(f"{file}: cannot be read as text ({exc})") from exc
    if (count := text.count(find)) != 1:
        raise Refused(f"{file}: the text to replace matches {count} times; it must match exactly once")

    path.write_bytes(text.replace(find, replace).encode())
    try:
        status = run_test()
    finally:
        path.write_bytes(original)

    if _dirty(repo):
        raise RuntimeError(f"{file} was restored, but the tree is still dirty: the test wrote something")
    return _PYTEST.get(status, Verdict.DID_NOT_RUN)
