"""The commit-msg gate must reject what a human typed, not what git generated.

CI-GATE-012 (#1145). `.github/hooks/validate-commit-msg.sh` applied one
Conventional Commits regex to every message, with no exemption for the messages
git writes itself. `git merge`, `git revert`, `git cherry-pick` and
`git commit --fixup` therefore all failed with their default messages.

Rejecting them protected nothing: this repo is squash-merge only
(`allow_merge_commit: false`), so a merge commit's message is discarded by the
squash and never reaches master. The message that does land is the squash title,
written by hand, and still gated.

The failure mode that made it worth fixing is not the friction. A refused merge
commit leaves the merge **staged but uncommitted** — git prints "Not committing
merge", which reads as a failed operation although the merge succeeded, inviting
a `git reset` that discards resolved conflicts. Hit on PR #1142.

These tests drive the hook through real `git` commands in a throwaway repo
rather than feeding it strings, because the exemption keys on git's own in-flight
state (`MERGE_HEAD` and friends) and only a real merge produces that state.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".github" / "hooks" / "validate-commit-msg.sh"


def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=30
    )


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A throwaway repo with the real hook installed, and one commit on it."""
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")

    hooks = r / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    installed = hooks / "commit-msg"
    shutil.copy(HOOK, installed)
    installed.chmod(0o755)

    (r / "base.txt").write_text("base\n", encoding="utf-8")
    _git(r, "add", "base.txt")
    assert _git(r, "commit", "-m", "feat: base").returncode == 0
    return r


def _commit(repo: pathlib.Path, name: str, message: str) -> subprocess.CompletedProcess[str]:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    return _git(repo, "commit", "-m", message)


class TestHandWrittenMessages:
    """The rule itself must survive: this is what the gate is for."""

    def test_conventional_message_is_accepted(self, repo: pathlib.Path) -> None:
        assert _commit(repo, "a.txt", "fix(make): a real change").returncode == 0

    @pytest.mark.parametrize(
        "message",
        ["not conventional at all", "Fix: capitalised type", "feat missing colon", ""],
    )
    def test_non_conventional_message_is_rejected(
        self, repo: pathlib.Path, message: str
    ) -> None:
        assert _commit(repo, "b.txt", message).returncode != 0

    def test_prose_beginning_with_merge_is_still_rejected(self, repo: pathlib.Path) -> None:
        """The reason the exemption keys on git state rather than on the text.

        A `"Merge "*` pattern would wave this through, and it is exactly the
        hand-written non-conventional message the gate exists to catch.
        """
        result = _commit(repo, "c.txt", "Merge strategy notes for the edge rollout")
        assert result.returncode != 0, (
            "a hand-written message starting with 'Merge' was exempted — the "
            "check is matching prose instead of git's in-flight state"
        )


class TestGitAuthoredMessages:
    """The four commands that generate their own message must work out of the box."""

    def test_merge_succeeds_with_its_default_message(self, repo: pathlib.Path) -> None:
        _git(repo, "checkout", "-q", "-b", "side")
        assert _commit(repo, "side.txt", "feat: side work").returncode == 0
        _git(repo, "checkout", "-q", "main")
        assert _commit(repo, "main.txt", "feat: main work").returncode == 0

        merge = _git(repo, "merge", "--no-ff", "side")
        assert merge.returncode == 0, f"merge refused: {merge.stdout}{merge.stderr}"
        assert not (repo / ".git" / "MERGE_HEAD").exists(), (
            "merge left MERGE_HEAD behind — it was staged but never committed, "
            "which is the half-finished state #1145 is about"
        )

    def test_revert_after_a_conflict_can_be_committed(self, repo: pathlib.Path) -> None:
        """Reverting *with a conflict* is the case that reaches the hook.

        Measured on git 2.53: a clean `git revert --no-edit` never runs
        `commit-msg` at all, so testing that path proves nothing about the
        exemption — it passes with the unfixed hook too. A conflicted revert
        stops and leaves `REVERT_HEAD`, and the operator's `git commit` to finish
        it *does* run the hook, with git's own "Revert ..." message.
        """
        f = repo / "conflict.txt"
        for n, msg in ((1, "feat: one"), (2, "feat: two"), (3, "feat: three")):
            f.write_text(f"{n}\n", encoding="utf-8")
            _git(repo, "add", "conflict.txt")
            assert _git(repo, "commit", "-m", msg).returncode == 0

        target = _git(repo, "rev-parse", "HEAD~1").stdout.strip()
        _git(repo, "revert", "--no-edit", target)
        assert (repo / ".git" / "REVERT_HEAD").exists(), "expected a conflicted revert"

        f.write_text("resolved\n", encoding="utf-8")
        _git(repo, "add", "conflict.txt")
        finish = _git(repo, "commit", "--no-edit")
        assert finish.returncode == 0, (
            f"could not finish the revert: {finish.stdout}{finish.stderr}"
        )

    def test_cherry_pick_after_a_conflict_can_be_committed(self, repo: pathlib.Path) -> None:
        """Same shape as the revert case, via CHERRY_PICK_HEAD.

        The source commit is deliberately created with `--no-verify` and a
        non-conventional message. Cherry-pick *reuses the original message*, so
        picking a commit this repo authored proves nothing — its message already
        passed the gate. The case the exemption exists for is a commit from
        somewhere the gate never governed.
        """
        f = repo / "pick.txt"
        f.write_text("main\n", encoding="utf-8")
        _git(repo, "add", "pick.txt")
        assert _git(repo, "commit", "-m", "feat: main side").returncode == 0

        _git(repo, "checkout", "-q", "-b", "pick-src", "HEAD~1")
        f.write_text("branch\n", encoding="utf-8")
        _git(repo, "add", "pick.txt")
        assert _git(repo, "commit", "--no-verify", "-m", "imported from elsewhere").returncode == 0
        sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

        _git(repo, "checkout", "-q", "main")
        _git(repo, "cherry-pick", sha)
        assert (repo / ".git" / "CHERRY_PICK_HEAD").exists(), "expected a conflicted cherry-pick"

        f.write_text("resolved\n", encoding="utf-8")
        _git(repo, "add", "pick.txt")
        finish = _git(repo, "commit", "--no-edit")
        assert finish.returncode == 0, (
            f"could not finish the cherry-pick: {finish.stdout}{finish.stderr}"
        )

    def test_fixup_succeeds(self, repo: pathlib.Path) -> None:
        sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "f.txt").write_text("f", encoding="utf-8")
        _git(repo, "add", "f.txt")
        fixup = _git(repo, "commit", "--fixup", sha)
        assert fixup.returncode == 0, f"fixup refused: {fixup.stdout}{fixup.stderr}"


def test_hook_is_executable_and_is_what_the_symlink_targets() -> None:
    """Guard the guard: the tests are worthless if they exercise a different file.

    `.git/hooks/commit-msg` is a symlink into `.github/hooks/`, so the tracked
    file is the one that actually runs. If that stops being true, these tests
    would still pass while the real hook went ungoverned.
    """
    assert HOOK.exists(), f"hook not found at {HOOK}"
    link = REPO_ROOT / ".git" / "hooks" / "commit-msg"
    if link.is_symlink():
        assert link.resolve() == HOOK.resolve(), (
            f"installed hook points at {link.resolve()}, not the tracked {HOOK}"
        )
