"""#2180 (TOOL-109): every active spec's pytest verification selects a test.

A `features.json` verification whose `-k` names a renamed test, or whose file was
renamed, collects nothing. It then reads as "pending", the same as a criterion
nobody has tried, and nothing says so until the spec tries to archive: on
2026-10-10 six of AI-009's fifteen commands selected no test at all.

Each command is collected, not run, and judged by pytest's exit code:

- 5, nothing collected: a selector that matches no test in files that exist.
  Never exempt; that is the defect.
- 4 with pytest's "not found:" error, a named file or test does not exist.
  Exempt only while the feature is `pending` AND listed in `UNWRITTEN`: its
  tests are not written yet, the TDD case. Neither the filesystem nor pytest's
  message tells an unwritten test from a renamed or deleted one, so the
  exemption is declared, and a listed feature whose tests now collect fails
  until it leaves the list. Any other exit 4 (a malformed `-k`, an unknown
  option) is a broken command whatever the state.

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

#: Pending features whose tests are not written yet. Add a TDD spec's ids here
#: when it lands; remove them when the tests do (a stale entry fails below).
UNWRITTEN = frozenset(
    {
        "AI-024-hermes-reach-f4",
        "AI-024-hermes-reach-f5",
        "AI-024-hermes-reach-f6",
        "AI-024-hermes-reach-f7",
        "AI-024-hermes-reach-f8",
        "AI-024-hermes-reach-f9",
        "BACKUP-057-f1",
        "BACKUP-057-f7",
        "GITOPS-003-f3",
        "GITOPS-003-f6",
        "TOOL-080-forge-pr-reviewer-f8",
    }
)


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


def verdict(returncode: int, state: str, output: str = "", unwritten: bool = False) -> str | None:
    """Why a command fails the guard, or None when it passes or is exempt."""
    if returncode == 0:
        return None
    if returncode == NO_TESTS_COLLECTED:
        return "selects no test"
    if returncode == USAGE_ERROR and "not found:" in output:
        if state == "pending" and unwritten:
            return None
        return "names a file or test that does not exist" + ("" if unwritten else " and is not in UNWRITTEN")
    if returncode == USAGE_ERROR:
        return "is not a valid pytest command"
    return f"pytest could not collect it (exit {returncode})"


MISSING = "ERROR: file or directory not found: tests/test_new.py"
MALFORMED = "ERROR: Wrong expression passed to '-k': a or: at column 5: expected not OR left parenthesis OR identifier"


@pytest.mark.parametrize(
    ("returncode", "state", "output", "unwritten", "fails"),
    [
        (0, "passing", "", False, False),
        (NO_TESTS_COLLECTED, "pending", "", True, True),
        (NO_TESTS_COLLECTED, "passing", "", False, True),
        (USAGE_ERROR, "pending", MISSING, True, False),
        # A pending feature whose test file was renamed or deleted: not declared, so reported.
        (USAGE_ERROR, "pending", MISSING, False, True),
        (USAGE_ERROR, "passing", MISSING, True, True),
        (USAGE_ERROR, "pending", MALFORMED, True, True),
        (2, "pending", "", True, True),
    ],
)
def test_the_verdict_exempts_only_unwritten_tests_of_a_pending_feature(
    returncode: int, state: str, output: str, unwritten: bool, fails: bool
) -> None:
    assert (verdict(returncode, state, output, unwritten) is not None) is fails


@pytest.mark.parametrize(
    ("args", "returncode"),
    [
        (("tests/test_that_was_never_written.py",), USAGE_ERROR),
        ((f"{Path(__file__).relative_to(REPO)}::test_that_was_never_written",), USAGE_ERROR),
        ((str(Path(__file__).relative_to(REPO)), "-k", "nothing_matches_this"), NO_TESTS_COLLECTED),
    ],
    ids=["missing-file", "missing-node-id", "empty-selection"],
)
def test_the_verdict_reads_what_pytest_actually_prints(args: tuple[str, ...], returncode: int) -> None:
    """The exemption keys on pytest's own words; pin them to the pytest installed, not to a fixture."""
    code, output = _collect(args)
    assert code == returncode, output
    # A missing file or test is the exempt shape; an empty selection never is.
    assert (verdict(code, "pending", output, unwritten=True) is None) is (code == USAGE_ERROR), output


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
            reason = verdict(returncode, state, output, feature_id in UNWRITTEN)
            if reason:
                failures.append(f"{feature_id}: `pytest {' '.join(args)}` {reason}")
    assert not failures, "\n".join(failures)


def test_every_unwritten_entry_is_still_unwritten() -> None:
    """The list only shrinks: an entry whose tests now collect has to leave it."""
    uses = {feature_id: args for args, features in _commands().items() for feature_id, _ in features}
    stale = []
    for feature_id in sorted(UNWRITTEN):
        if feature_id not in uses:
            stale.append(f"{feature_id}: no active spec verification has this id")
            continue
        returncode, output = _collect(uses[feature_id])
        if not (returncode == USAGE_ERROR and "not found:" in output):
            stale.append(f"{feature_id}: its tests collect now (exit {returncode})")
    assert not stale, "\n".join(stale)


#: What `dotf spec init` writes into a new feature's `verification` (dotfiles repo: this regex
#: must track it, so re-check it when that scaffold changes). Pending, it is
#: the honest state of a criterion nobody has tried; in an archived spec it is a
#: criterion that was closed over without ever being verified (#2308).
SCAFFOLD_VERIFICATION = re.compile(r"^\s*echo\s+['\"]not implemented['\"]\s*&&\s*exit\s+1\s*$")


def scaffold_features(spec_root: Path) -> list[str]:
    """Ids of the features, in archived specs under `spec_root`, still carrying the scaffold."""
    found = []
    for path in sorted(spec_root.glob("archive/*/features.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        # One old archive wraps its list as {"spec": ..., "features": [...]}.
        for feature in loaded["features"] if isinstance(loaded, dict) else loaded:
            if SCAFFOLD_VERIFICATION.match(feature.get("verification", "")):
                found.append(f"{path.parent.name}: {feature['id']}")
    return found


@pytest.mark.parametrize(
    ("verification", "is_scaffold"),
    [
        ("echo 'not implemented' && exit 1", True),
        ('echo "not implemented" && exit 1', True),
        ("poetry run pytest tests/test_x.py -q", False),
        ("echo 'not implemented yet' && exit 1", False),
    ],
)
def test_the_scaffold_is_recognised_by_its_shape(verification: str, is_scaffold: bool) -> None:
    assert bool(SCAFFOLD_VERIFICATION.match(verification)) is is_scaffold


def test_the_guard_finds_a_scaffold_planted_in_an_archived_spec(tmp_path: Path) -> None:
    spec = tmp_path / "archive" / "X-001"
    spec.mkdir(parents=True)
    features = [
        {"id": "X-001-f1", "verification": "poetry run pytest tests/x.py"},
        {"id": "X-001-f2", "verification": "echo 'not implemented' && exit 1"},
    ]
    (spec / "features.json").write_text(json.dumps(features), encoding="utf-8")
    assert scaffold_features(tmp_path) == ["X-001: X-001-f2"]


def test_no_archived_spec_keeps_the_scaffold_verification() -> None:
    """An archived spec closed over a criterion nobody verified: the reviewer caught it once by hand (TOOL-082)."""
    # A floor, so a moved archive or a changed layout cannot turn the guard into a no-op.
    assert len(list(SPECS.glob("archive/*/features.json"))) >= 10
    assert not scaffold_features(SPECS)
