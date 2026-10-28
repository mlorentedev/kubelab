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


def test_the_lock_is_tracked_and_not_ignored() -> None:
    assert _git("ls-files", "--error-unmatch", "poetry.lock").returncode == 0, "poetry.lock is not tracked"
    # --no-index: a tracked file is otherwise never reported, so a pattern re-added later would pass.
    ignored = _git("check-ignore", "--no-index", "-v", "poetry.lock")
    assert ignored.returncode == 1, f"poetry.lock is ignored again: {ignored.stdout.strip()}"


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
