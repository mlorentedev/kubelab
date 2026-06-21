"""Tests for SOPS age-key auto-discovery (toolkit/core/sops.py).

Guards the recurrence where a fresh shell without SOPS_AGE_KEY_FILE fails to
decrypt because the key lives at ~/.config/age/key.txt, not the sops default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.core import sops


class TestResolveAgeKeyFile:
    def test_honors_existing_override(self, tmp_path: Path) -> None:
        key = tmp_path / "explicit.txt"
        key.write_text("k")
        assert sops.resolve_age_key_file({"SOPS_AGE_KEY_FILE": str(key)}) == str(key)

    def test_falls_through_when_override_points_nowhere(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        conv = tmp_path / ".config" / "age" / "key.txt"
        conv.parent.mkdir(parents=True)
        conv.write_text("k")
        env = {"SOPS_AGE_KEY_FILE": str(tmp_path / "nope.txt")}
        assert sops.resolve_age_key_file(env) == str(conv)

    def test_prefers_sops_default_over_repo_convention(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        default = tmp_path / ".config" / "sops" / "age" / "keys.txt"
        default.parent.mkdir(parents=True)
        default.write_text("k")
        conv = tmp_path / ".config" / "age" / "key.txt"
        conv.parent.mkdir(parents=True)
        conv.write_text("k")
        assert sops.resolve_age_key_file({}) == str(default)

    def test_returns_none_when_no_key_anywhere(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert sops.resolve_age_key_file({}) is None


class TestAgeKeyEnv:
    def test_sets_var_when_key_found_and_preserves_base_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        conv = tmp_path / ".config" / "age" / "key.txt"
        conv.parent.mkdir(parents=True)
        conv.write_text("k")
        out = sops.age_key_env({"PATH": "/x"})
        assert out["SOPS_AGE_KEY_FILE"] == str(conv)
        assert out["PATH"] == "/x"

    def test_returns_base_env_unchanged_when_no_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        out = sops.age_key_env({"PATH": "/x"})
        assert "SOPS_AGE_KEY_FILE" not in out
        assert out == {"PATH": "/x"}
