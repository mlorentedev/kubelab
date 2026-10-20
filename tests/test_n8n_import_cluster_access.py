"""#2201: an import on a workstation that cannot reach the cluster fails legibly.

On the macmini `make import-n8n ENV=prod` ended in a `FileNotFoundError`
traceback, because kubectl was not installed. Now each kubectl call reports what
is missing and the run returns False, the non-zero exit, without a traceback.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.test_n8n_shared_credentials import REPO_ROOT, _Cm, _vault
from toolkit.features import n8n_import


def _run_import(monkeypatch: pytest.MonkeyPatch, kubectl: Any, kubeconfig: Path) -> bool:
    monkeypatch.setattr(n8n_import, "ConfigurationManager", lambda *a, **k: _Cm(_vault()))
    monkeypatch.setattr(n8n_import.subprocess, "run", kubectl)
    monkeypatch.setattr(n8n_import, "_kubeconfig_for", lambda env: str(kubeconfig))
    monkeypatch.setattr(n8n_import, "_wait_rollout_ready", lambda *a, **k: False)
    return n8n_import.import_n8n_workflow("prod", REPO_ROOT)


def test_no_kubectl_fails_the_run_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def absent(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", cmd[0])

    kubeconfig = tmp_path / "config"
    kubeconfig.touch()
    assert _run_import(monkeypatch, absent, kubeconfig) is False
    out = "".join(capsys.readouterr())
    assert "kubectl is not on PATH" in out
    assert "Traceback" not in out


def test_a_missing_kubeconfig_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def refused(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, cmd, stderr="error: stat config: no such file or directory")

    missing = tmp_path / "absent-config"
    assert _run_import(monkeypatch, refused, missing) is False
    out = "".join("".join(capsys.readouterr()).split())
    assert f"kubeconfigmissingat{missing}" in out


def test_an_existing_kubeconfig_gets_no_hint(tmp_path: Path) -> None:
    present = tmp_path / "config"
    present.touch()
    assert n8n_import._kubeconfig_hint(["kubectl", "get", "pods", "--kubeconfig", str(present)], "prod") == ""
    assert n8n_import._kubeconfig_hint(["kubectl", "get", "pods"], "prod") == ""


def test_every_kubectl_call_reports_a_missing_kubectl(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_run` reports a missing kubectl; the next test proves every call goes through a handler like it."""

    def absent(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", cmd[0])

    monkeypatch.setattr(n8n_import.subprocess, "run", absent)
    assert n8n_import._run(["kubectl", "rollout", "status", "deploy/n8n"], env="prod") is False
    assert "kubectl is not on PATH" in "".join(capsys.readouterr())


def _guarded(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    """Whether a `try` around this very call catches `FileNotFoundError`."""
    node: ast.AST = call
    while node in parents:
        child, node = node, parents[node]
        if isinstance(node, ast.FunctionDef):
            return False
        if isinstance(node, ast.Try) and child in node.body:
            if any(h.type is not None and "FileNotFoundError" in ast.unparse(h.type) for h in node.handlers):
                return True
    return False


def test_every_subprocess_call_handles_a_missing_kubectl() -> None:
    """The exec, the restart and the rollout wait spawn through `_run`, not on their own.

    Measured on the source rather than by calling each path: every call into
    `subprocess` must sit inside a `try` of its own function that catches
    `FileNotFoundError`. A handler elsewhere in the function does not count.
    """
    tree = ast.parse(Path(n8n_import.__file__).read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    spawns = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and ast.unparse(call.func).startswith("subprocess.")
    ]
    assert spawns, "the scan found no subprocess call; it measures nothing"
    unguarded = [f"line {call.lineno}" for call in spawns if not _guarded(call, parents)]
    assert not unguarded, unguarded


def test_a_handler_beside_the_call_does_not_count() -> None:
    """The guard's own contract: a `try` elsewhere in the function is not cover."""
    tree = ast.parse(
        "def f():\n"
        "    try:\n        open('x')\n    except FileNotFoundError:\n        pass\n"
        "    subprocess.run(['kubectl'])\n"
    )
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    call = next(c for c in ast.walk(tree) if isinstance(c, ast.Call) and ast.unparse(c.func) == "subprocess.run")
    assert not _guarded(call, parents)


def test_a_failed_import_exits_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ticket asks for a non-zero exit, so measure the command, not only the bool."""
    from typer.testing import CliRunner

    from toolkit.cli import infra

    monkeypatch.setattr(infra, "validate_environment_config", lambda _env: None)
    monkeypatch.setattr(n8n_import, "import_n8n_workflow", lambda *a, **k: False)
    run = CliRunner().invoke(infra.app, ["n8n", "import", "--env", "prod"])
    assert run.exit_code == 1, run.output


@pytest.mark.parametrize(
    "tail",
    [["--kubeconfig"], ["--kubeconfig="]],
    ids=["flag-last", "empty-value"],
)
def test_the_hint_never_raises_on_a_short_command(tail: list[str]) -> None:
    assert n8n_import._kubeconfig_hint(["kubectl", "get", "pods", *tail], "prod") == ""


def test_the_hint_reads_the_equals_spelling(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    hint = n8n_import._kubeconfig_hint(["kubectl", f"--kubeconfig={missing}"], "staging")
    assert str(missing) in hint
    # The advice is the command to run, with the environment already filled in.
    assert "make fetch-kubeconfig ENV=staging" in hint
