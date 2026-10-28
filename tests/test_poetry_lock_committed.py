"""The toolkit's dependencies come from a committed lock, never from a range (TOOL-125, #2739).

`poetry.lock` was gitignored from the scaffold on, so every CI run resolved the
ranges in pyproject.toml afresh. On 2026-10-28 pytest 9.2.0 reached CI four hours
after its upload and broke every open PR at once, none of which had changed a
dependency. A committed lock means a new release reaches CI only through a PR.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)


def _ignoring_pattern(cwd: pathlib.Path) -> str | None:
    """The pattern that ignores poetry.lock in `cwd`, or None when nothing does.

    --no-index: a tracked file is otherwise never reported, so a pattern re-added later would pass.
    The verdict comes from the plain form, because with -v a negation (`!poetry.lock`) exits 0 as well.
    """
    check = ["git", "check-ignore", "--no-index"]
    if subprocess.run([*check, "poetry.lock"], cwd=cwd, capture_output=True, check=False).returncode != 0:
        return None
    verbose = subprocess.run([*check, "-v", "poetry.lock"], cwd=cwd, capture_output=True, text=True, check=False)
    return verbose.stdout.strip()


def test_the_lock_is_tracked_and_not_ignored() -> None:
    assert _git("ls-files", "--error-unmatch", "poetry.lock").returncode == 0, "poetry.lock is not tracked"
    assert _ignoring_pattern(REPO) is None, f"poetry.lock is ignored again: {_ignoring_pattern(REPO)}"


def test_a_negated_pattern_is_not_read_as_ignoring_the_lock(tmp_path: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("*.lock\n!poetry.lock\n")
    assert _ignoring_pattern(tmp_path) is None
    (tmp_path / ".gitignore").write_text("*.lock\n")
    assert _ignoring_pattern(tmp_path) == ".gitignore:1:*.lock\tpoetry.lock"


def test_the_lock_matches_pyproject() -> None:
    poetry = shutil.which("poetry")
    assert poetry, "poetry is not on PATH, so the lock cannot be checked"
    done = subprocess.run([poetry, "check", "--lock"], cwd=REPO, capture_output=True, text=True, check=False)
    assert done.returncode == 0, f"run `poetry lock` and commit it: {(done.stdout + done.stderr)[-1000:]}"


def test_dependabot_waits_before_proposing_a_python_release() -> None:
    config = yaml.safe_load((REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    pip = [u for u in config["updates"] if u["package-ecosystem"] == "pip"]
    assert len(pip) == 1, pip
    cooldown = pip[0].get("cooldown", {})
    # Three days: long enough for a broken upload to be yanked or fixed, as pytest 9.2.0 was within a day.
    assert cooldown.get("default-days", 0) >= 3, pip[0]
    # A per-semver key overrides the default for its class, so one set lower would reopen the window.
    assert all(v >= 3 for k, v in cooldown.items() if k.startswith("semver-")), cooldown
