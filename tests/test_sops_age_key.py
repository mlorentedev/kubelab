"""Tests for SOPS age-key auto-discovery (toolkit/core/sops.py).

Guards the recurrence where a fresh shell without SOPS_AGE_KEY_FILE fails to
decrypt because the key lives at ~/.config/age/key.txt, not the sops default.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from toolkit.core import sops

TOOLKIT_ROOT = Path(__file__).resolve().parents[1] / "toolkit"
_SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_call", "check_output"}


def _is_sops_command(call: ast.Call) -> bool:
    """True when the first positional arg is a list literal whose head is ``"sops"``."""
    if not call.args:
        return False
    first = call.args[0]
    if not isinstance(first, ast.List) or not first.elts:
        return False
    head = first.elts[0]
    return isinstance(head, ast.Constant) and head.value == "sops"


def _is_subprocess_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):  # subprocess.run(...)
        return func.attr in _SUBPROCESS_FUNCS
    if isinstance(func, ast.Name):  # run(...) after ``from subprocess import run``
        return func.id in _SUBPROCESS_FUNCS
    return False


def _subtree_has_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _subtree_has_os_environ(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr == "environ":
            if isinstance(n.value, ast.Name) and n.value.id == "os":
                return True
    return False


def _iter_sops_calls():
    """Yield (relative_path, ast.Call) for every direct ``sops`` subprocess call under toolkit/."""
    for py in sorted(TOOLKIT_ROOT.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_subprocess_call(node) and _is_sops_command(node):
                yield py.relative_to(TOOLKIT_ROOT.parent), node


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


class TestSopsCallsUseAgeKeyEnv:
    """Regression guard (TOOL-017/C1/C10): every ``sops`` subprocess must run with an
    explicit ``env=`` derived from ``age_key_env()`` — never a bare/implicit ``os.environ``.

    Otherwise decryption silently fails on a fresh shell where the age key sits only at
    the repo-convention path, and callers (e.g. ``make deploy-argocd``) feed blank
    secrets downstream.
    """

    def test_at_least_one_sops_call_is_scanned(self) -> None:
        # Guards the guard: if the AST matcher stops finding sops calls, the test is
        # silently vacuous. There are several real sops subprocess sites under toolkit/.
        assert sum(1 for _ in _iter_sops_calls()) >= 5

    def test_every_sops_subprocess_uses_age_key_env(self) -> None:
        offenders: list[str] = []
        for rel, call in _iter_sops_calls():
            env_kw = next((kw for kw in call.keywords if kw.arg == "env"), None)
            if env_kw is None:
                offenders.append(f"{rel}:{call.lineno} — no env= (subprocess inherits os.environ)")
                continue
            if _subtree_has_name(env_kw.value, "age_key_env"):
                continue
            if _subtree_has_os_environ(env_kw.value):
                offenders.append(f"{rel}:{call.lineno} — env=os.environ bypasses age_key_env()")
        assert not offenders, "sops subprocess calls must use age_key_env():\n  " + "\n  ".join(offenders)
