"""#2180 (TOOL-109): every active spec's pytest verification selects a test.

A `features.json` verification whose `-k` names a renamed test, or whose file was
renamed, collects nothing. It then reads as "pending", the same as a criterion
nobody has tried, and nothing says so until the spec tries to archive: on
2026-10-10 six of AI-009's fifteen commands selected no test at all.

Each command is collected, not run, and judged by pytest's exit code:

- 5, nothing collected: a selector that matches no test in files that exist.
  Never exempt; that is the defect.
- 4 with pytest's "not found:" error, a named file or test does not exist.
  Exempt only while the feature is `pending`: its tests are not written yet,
  the TDD case. Any other exit 4 (a malformed `-k`, an unknown option) is a
  broken command whatever the state.

A shell redirection after the arguments (`2>&1`, `> out.txt`) is not part of
them and is cut before splitting.

A live-only command declares itself with `-m infra` (or `-m e2e`), which also
makes it collect, so it needs no exemption of its own.

Marked `integration`: it spawns one pytest per distinct command, about ten
seconds in all, so it runs in CI's `make test` and stays out of `make test-fast`.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPECS = REPO / "specs"
_PYTEST = re.compile(r"poetry run pytest\b([^&|;]*)")
_REDIRECT = re.compile(r"\s\d*>")
NO_TESTS_COLLECTED = 5
USAGE_ERROR = 4

pytestmark = pytest.mark.integration


def _commands() -> dict[tuple[str, ...], list[tuple[str, str]]]:
    """Each distinct pytest argument list, with the (feature id, state) pairs using it."""
    found: dict[tuple[str, ...], list[tuple[str, str]]] = {}
    # Active specs only: `specs/archive/*/` is one level deeper and not globbed.
    for path in sorted(SPECS.glob("*/features.json")):
        for feature in json.loads(path.read_text(encoding="utf-8")):
            for match in _PYTEST.finditer(feature.get("verification", "")):
                args = tuple(shlex.split(_REDIRECT.split(match.group(1), maxsplit=1)[0]))
                found.setdefault(args, []).append((feature["id"], feature.get("state", "")))
    return found


def _collect(args: tuple[str, ...]) -> tuple[int, str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-qq", "--no-cov", "-p", "no:cacheprovider", *args]
    run = subprocess.run(command, cwd=REPO, capture_output=True, text=True, check=False)
    return run.returncode, run.stdout + run.stderr


def verdict(returncode: int, state: str, output: str = "") -> str | None:
    """Why a command fails the guard, or None when it passes or is exempt."""
    if returncode == 0:
        return None
    if returncode == NO_TESTS_COLLECTED:
        return "selects no test"
    if returncode == USAGE_ERROR and "not found:" in output:
        return None if state == "pending" else "names a file or test that does not exist"
    if returncode == USAGE_ERROR:
        return "is not a valid pytest command"
    return f"pytest could not collect it (exit {returncode})"


MISSING = "ERROR: file or directory not found: tests/test_new.py"
MALFORMED = "ERROR: Wrong expression passed to '-k': a or: at column 5: expected not OR left parenthesis OR identifier"


@pytest.mark.parametrize(
    ("returncode", "state", "output", "fails"),
    [
        (0, "passing", "", False),
        (NO_TESTS_COLLECTED, "pending", "", True),
        (NO_TESTS_COLLECTED, "passing", "", True),
        (USAGE_ERROR, "pending", MISSING, False),
        (USAGE_ERROR, "passing", MISSING, True),
        (USAGE_ERROR, "pending", MALFORMED, True),
        (2, "pending", "", True),
    ],
)
def test_the_verdict_exempts_only_unwritten_tests_of_a_pending_feature(
    returncode: int, state: str, output: str, fails: bool
) -> None:
    assert (verdict(returncode, state, output) is not None) is fails


@pytest.mark.parametrize("redirect", [" 2>&1", " > out.txt", " 2> err.txt"])
def test_a_redirection_is_not_an_argument(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, redirect: str) -> None:
    spec = tmp_path / "X-001"
    spec.mkdir()
    feature = {"id": "f1", "state": "passing", "verification": f"poetry run pytest tests/x.py -q{redirect} | tee log"}
    (spec / "features.json").write_text(json.dumps([feature]), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "SPECS", tmp_path)
    assert list(_commands()) == [("tests/x.py", "-q")]


def test_active_specs_carry_pytest_verifications() -> None:
    """A floor, so the guard below cannot pass by finding nothing."""
    assert len(_commands()) >= 10


def test_every_verification_selects_a_test() -> None:
    failures = []
    for args, features in _commands().items():
        returncode, output = _collect(args)
        for feature_id, state in features:
            reason = verdict(returncode, state, output)
            if reason:
                failures.append(f"{feature_id}: `pytest {' '.join(args)}` {reason}")
    assert not failures, "\n".join(failures)
