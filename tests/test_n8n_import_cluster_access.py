"""#2201: an import on a workstation that cannot reach the cluster fails legibly.

On the macmini `make import-n8n ENV=prod` ended in a `FileNotFoundError`
traceback, because kubectl was not installed. Now each kubectl call reports what
is missing and the run returns False, the non-zero exit, without a traceback.
"""

from __future__ import annotations

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
    out = capsys.readouterr().out
    assert "kubectl is not on PATH" in out
    assert "Traceback" not in out


def test_a_missing_kubeconfig_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def refused(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, cmd, stderr="error: stat config: no such file or directory")

    missing = tmp_path / "absent-config"
    assert _run_import(monkeypatch, refused, missing) is False
    out = "".join(capsys.readouterr().out.split())
    assert f"kubeconfigmissingat{missing}" in out


def test_an_existing_kubeconfig_gets_no_hint(tmp_path: Path) -> None:
    present = tmp_path / "config"
    present.touch()
    assert n8n_import._kubeconfig_hint(["kubectl", "get", "pods", "--kubeconfig", str(present)]) == ""
    assert n8n_import._kubeconfig_hint(["kubectl", "get", "pods"]) == ""


def test_every_kubectl_call_reports_a_missing_kubectl(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_run` carries the exec, the restart and the rollout wait, not only the pod list."""

    def absent(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", cmd[0])

    monkeypatch.setattr(n8n_import.subprocess, "run", absent)
    assert n8n_import._run(["kubectl", "rollout", "status", "deploy/n8n"]) is False
    assert "kubectl is not on PATH" in capsys.readouterr().out
