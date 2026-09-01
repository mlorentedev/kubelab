"""TOOL-045 (#1462) AC4 — the pre-push guard, exercised without touching the network.

The guard refuses a push that would recreate a branch whose PR is already merged
or closed (lesson-402). It was verified during development against real pull
requests, which is evidence but is **not** what AC4 asks for and is not a
regression guard: it needs GitHub to be up, the shell to be authenticated, and
those specific PRs to keep their state forever.

So `gh` is replaced with a script on `PATH`. That is the honest seam — the guard's
entire input is what `gh pr list` prints, and faking the binary tests the real
`check_merged_branch` rather than a reimplementation of it in Python.

**The fail-open path is tested too, and that is the half most likely to rot.**
The guard deliberately allows the push when `gh` is missing, unauthenticated or
offline (#1462 AC3): it prevents an orphaned commit, not a security property, and
one that blocked every push during a GitHub outage would be switched off within a
week. A later edit that "tightens" it into failing closed would be invisible
without this test, right up until the next outage stopped everyone from pushing.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".github/hooks/pre-push.sh"

#: Absolute, because the tests below narrow PATH to a directory holding only a
#: fake `gh` — "bash" would not resolve through it either.
BASH = shutil.which("bash") or "/bin/bash"

ZERO = "0" * 40
SHA = "a" * 40

#: A ref-update line as git feeds it to a pre-push hook on stdin:
#: `<local ref> <local sha> <remote ref> <remote sha>`. An all-zero REMOTE sha is
#: the case that matters — the branch is absent there, so the push would create it.
RECREATE = f"refs/heads/some-branch {SHA} refs/heads/some-branch {ZERO}\n"


def _fake_gh(tmp_path: Path, body: str) -> Path:
    """A `gh` on PATH that behaves as the test needs, with no network anywhere."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!{BASH}\n{body}\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _guard_source() -> str:
    """The guard function's own text, lifted out of the hook.

    Extracted in PYTHON rather than with `sed` inside the shell, so the script
    handed to bash needs no external binary at all. That is what lets `PATH` be
    set to a directory containing only the fake `gh` — the first version used
    `sed`, so `PATH` had to include `/usr/bin`, where the developer's REAL `gh`
    lives. The "gh is not installed" test then found it, queried GitHub for real,
    and passed for the wrong reason (empty result, exit 0, no warning).
    """
    text = HOOK.read_text(encoding="utf-8")
    start = text.index("check_merged_branch() {")
    end = text.index("\n}\n", start) + len("\n}\n")
    return text[start:end]


def _run(bin_dir: Path | None, stdin: str = RECREATE) -> subprocess.CompletedProcess[str]:
    """Run ONLY the guard function, not the whole hook.

    Sourcing just the function keeps `make lint` — the hook's other half — out of
    a unit test.
    """
    script = f"{_guard_source()}\ncheck_merged_branch origin"
    env = dict(os.environ)
    # PATH holds the fake `gh` and NOTHING else, so a real one cannot answer.
    # bash itself is invoked by ABSOLUTE path for the same reason: with PATH
    # narrowed this far, resolving "bash" through it fails too.
    env["PATH"] = str(bin_dir) if bin_dir else ""
    return subprocess.run(
        [BASH, "-c", script], input=stdin, capture_output=True, text=True, env=env
    )


def test_the_hook_exists_and_defines_the_guard() -> None:
    """Pins the two things every test below silently depends on."""
    assert HOOK.exists(), f"the pre-push hook moved: {HOOK}"
    assert "check_merged_branch()" in HOOK.read_text(encoding="utf-8")
    assert "gh pr list" in _guard_source(), "the extracted function is not the guard"


# --- AC4, first half: the refusal, with no network -----------------------------


def test_a_merged_prs_branch_is_refused(tmp_path: Path) -> None:
    result = _run(_fake_gh(tmp_path, 'echo "1511 MERGED"'))

    assert result.returncode == 1
    assert "1511" in result.stdout
    assert "MERGED" in result.stdout


def test_a_closed_prs_branch_is_refused(tmp_path: Path) -> None:
    """AC1 says MERGED *or* CLOSED. A closed PR's branch, deleted by hand, is
    identical in consequence: the commit lands where no PR is looking."""
    result = _run(_fake_gh(tmp_path, 'echo "1513 CLOSED"'))

    assert result.returncode == 1
    assert "1513" in result.stdout and "CLOSED" in result.stdout


def test_the_refusal_names_what_to_do_instead(tmp_path: Path) -> None:
    """AC1 asks for the remedy, not just the diagnosis.

    A guard that only says no teaches people to reach for --no-verify.
    """
    result = _run(_fake_gh(tmp_path, 'echo "1511 MERGED"'))

    assert "checkout -b" in result.stdout
    assert "cherry-pick" in result.stdout


# --- AC2: the controls. Without these, a guard that refuses everything passes ---


def test_a_brand_new_branch_is_allowed(tmp_path: Path) -> None:
    """No PR at all: `gh` prints nothing and exits 0. This is a first push."""
    result = _run(_fake_gh(tmp_path, "true"))

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_an_update_to_an_existing_remote_branch_is_allowed(tmp_path: Path) -> None:
    """Non-zero REMOTE sha: the branch is still there, so nothing is being recreated.

    The guard must not even ask, which is why the fake `gh` would refuse if it ran.
    """
    stdin = f"refs/heads/b {SHA} refs/heads/b {SHA}\n"
    result = _run(_fake_gh(tmp_path, 'echo "1511 MERGED"'), stdin=stdin)

    assert result.returncode == 0


def test_deleting_a_merged_branch_is_allowed(tmp_path: Path) -> None:
    """All-zero LOCAL sha is a deletion — exactly the cleanup this encourages."""
    stdin = f"refs/heads/b {ZERO} refs/heads/b {SHA}\n"
    result = _run(_fake_gh(tmp_path, 'echo "1511 MERGED"'), stdin=stdin)

    assert result.returncode == 0


# --- AC4, second half: fail open. The half most likely to rot ------------------


def test_an_unreachable_forge_warns_and_allows(tmp_path: Path) -> None:
    """AC3. `gh` exits non-zero — offline, rate-limited, or not authenticated."""
    result = _run(_fake_gh(tmp_path, "exit 1"))

    assert result.returncode == 0
    assert "WARN" in result.stdout


def test_gh_not_installed_warns_and_allows() -> None:
    """The other fail-open case: no `gh` binary at all."""
    result = _run(None)

    assert result.returncode == 0
    assert "WARN" in result.stdout
    assert "gh not installed" in result.stdout
