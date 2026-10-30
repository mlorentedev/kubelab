"""Prove a guard goes red against one mutation, without a way to lose work (TOOL-100, #2104).

The procedure this replaces was a shell line: commit, mutate, run the test,
`git checkout HEAD -- <file>`. Its safety rested on the commit having landed, and
a commit a pre-commit hook refuses leaves HEAD where it was, so the restore then
reset the file to an older version (lesson-480, four recurrences). Here the
restore does not depend on HEAD at all: the file's own bytes are kept in memory
and written back, and a dirty tree is refused before anything is touched.

A verdict is a comparison, and so needs both sides: the test must pass against
the unmutated file before it is run against the mutant. A target that is already
failing goes red against every mutation, so without the baseline it certifies
each one as caught (measured 2026-10-13, lesson-565: two unrelated red tests made
every mutant of a Terraform-runner test read RED, one of which the correct
baseline showed GREEN).
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
_NOTHING_COLLECTED = 5


def _dirty(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def run(repo: Path, file: Path, find: str, replace: str, run_test: Callable[[], int]) -> Verdict:
    """Replace the one occurrence of `find` in `file`, run the test, put the file back.

    Refuses on a dirty tree: the clean tree is what makes "put it back" the same
    as "as it was committed", and what keeps uncommitted work out of reach. It
    also refuses, before mutating, a test that does not exit 0 against the
    unmutated file: a red baseline proves nothing, since it is red against every
    mutant too. The file is restored from the bytes read here, in a `finally`, so
    an interrupted test restores it too.

    The target test must be idempotent across two runs in one invocation: state is
    not reset between the baseline and the mutant run, so a test that leaves files
    or other state behind can fail the second run for that reason and read RED.
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

    if (baseline := run_test()) == _NOTHING_COLLECTED:
        raise Refused(
            f"{file}: pytest collected no test (pytest exit 5), so there is nothing to compare. The usual "
            'cause is a marker the repository\'s addopts deselect (`-m "not e2e and not infra"`): name it in '
            "the target, e.g. TEST='tests/infra/x.py -m infra'. A `-m` given there overrides the default."
        )
    if baseline != 0:
        raise Refused(
            f"{file}: the test does not pass without the mutation (pytest exit {baseline}), so its result "
            "against a mutant proves nothing: a red baseline is red against every mutation. Deselect the "
            "unrelated failures (e.g. TEST='tests/x.py -k <passing tests>') and run again."
        )

    path.write_bytes(text.replace(find, replace).encode())
    try:
        status = run_test()
    finally:
        path.write_bytes(original)

    if _dirty(repo):
        raise RuntimeError(f"{file} was restored, but the tree is still dirty: the test wrote something")
    return _PYTEST.get(status, Verdict.DID_NOT_RUN)
