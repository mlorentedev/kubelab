"""TOOL-086 (#1863): one import run, one restart, and every exec lands on a live pod.

`import-n8n` restarted n8n after EACH workflow, so a four-workflow run bounced the
pod four times. #1863 measured `multi-forge-sync.json` failing with `command
terminated` right after `notify-router.json`'s restart, and hypothesised that
the exec landed on the terminating pod.

The fix has two halves, and each is tested here against a fake `kubectl`:

- the workflows are all imported and published first, then n8n restarts once;
- every exec targets a named pod that is Running, Ready and not being deleted,
  and a failure names that pod and what the pod says about itself afterwards.

The hypothesis was not the whole cause. With both halves in place, one failure
recurred on a pod that was Ready when chosen (#1892): the container itself died
mid-import. The pod's restart count and last termination are what tell that
apart from an import error, so a failed exec reports them (#1902).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from toolkit.features.configuration import ConfigurationManager
from toolkit.features.n8n_import import N8N_IMPORT_CATALOG, N8N_SHARED_CREDENTIALS, import_n8n_workflow

REPO_ROOT = Path(__file__).resolve().parent.parent

READY = "n8n-7c9d-live"
TERMINATING = "n8n-5b2a-old"


def _pod(name: str, *, ready: bool = True, deleting: bool = False) -> dict[str, Any]:
    meta: dict[str, Any] = {"name": name}
    if deleting:
        meta["deletionTimestamp"] = "2026-09-27T20:00:00Z"
    return {
        "metadata": meta,
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]},
    }


class _Kubectl:
    """Records every command; answers `get pods` from `pods`, fails what `fail` matches."""

    def __init__(self, pods: list[dict[str, Any]], fail: str | None = None) -> None:
        self.pods = pods
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        if cmd[1:3] == ["get", "pods"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"items": self.pods}), stderr="")
        if self.fail and self.fail in (kwargs.get("input") or "") + " ".join(cmd):
            raise subprocess.CalledProcessError(1, cmd, stderr="command terminated with exit code 137")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def of(self, verb: str) -> list[int]:
        return [i for i, c in enumerate(self.calls) if verb in " ".join(c)]

    def exec_targets(self) -> set[str]:
        return {c[c.index("--kubeconfig") - 1] for c in self.calls if c[1] == "exec"}


def _import(kubectl: _Kubectl) -> bool:
    cm = MagicMock()
    cm.get_secret_by_path.return_value = "dummy-secret-token"
    cm.get_merged_config.return_value = ConfigurationManager(env="staging").get_merged_config()
    with (
        patch("toolkit.features.n8n_import.ConfigurationManager", return_value=cm),
        patch("toolkit.features.n8n_import.subprocess.run", side_effect=kubectl),
    ):
        return import_n8n_workflow("staging", REPO_ROOT)


def test_one_run_restarts_n8n_once_after_every_publish() -> None:
    kubectl = _Kubectl([_pod(READY)])
    assert _import(kubectl) is True
    restarts = kubectl.of("rollout restart")
    publishes = kubectl.of("publish:workflow")
    assert len(publishes) == len([s for s in N8N_IMPORT_CATALOG if "staging" in s.envs])
    assert len(restarts) == 1, f"{len(restarts)} restarts in one run"
    assert restarts[0] > max(publishes), "the restart must follow the last publish"


def test_every_exec_lands_on_the_ready_pod_never_the_terminating_one() -> None:
    kubectl = _Kubectl([_pod(TERMINATING, deleting=True), _pod("n8n-starting", ready=False), _pod(READY)])
    assert _import(kubectl) is True
    assert kubectl.exec_targets() == {f"pod/{READY}"}


def test_no_live_pod_fails_the_run_without_an_exec(capsys: pytest.CaptureFixture[str]) -> None:
    kubectl = _Kubectl([_pod(TERMINATING, deleting=True)])
    assert _import(kubectl) is False
    assert kubectl.of("exec") == []
    assert kubectl.of("rollout restart") == [], "nothing imported, nothing to restart"
    assert "no Ready n8n pod" in " ".join(capsys.readouterr().out.split())


def test_a_failed_workflow_fails_the_run_and_the_others_still_go_live(capsys: pytest.CaptureFixture[str]) -> None:
    kubectl = _Kubectl([_pod(READY)], fail="multi-forge-sync")
    assert _import(kubectl) is False
    assert len(kubectl.of("rollout restart")) == 1, "the workflows that imported still need the restart"
    out = " ".join(capsys.readouterr().out.split())
    assert f"pod/{READY}" in out, "a failing exec must name the pod it ran against"


def test_the_pod_selector_mirrors_the_deployment() -> None:
    """The selector is declared on the spec because an exec needs a pod, not a
    Deployment. It must equal what the Deployment itself selects."""
    docs = list(yaml.safe_load_all((REPO_ROOT / "infra/k8s/base/services/n8n.yaml").read_text()))
    deployment = next(d for d in docs if d and d.get("kind") == "Deployment")
    labels = deployment["spec"]["selector"]["matchLabels"]
    expected = ",".join(f"{k}={v}" for k, v in labels.items())
    assert {spec.pod_selector for spec in N8N_IMPORT_CATALOG} == {expected}
    assert {cred.pod_selector for cred in N8N_SHARED_CREDENTIALS} == {expected}


def test_a_failed_exec_reports_why_the_container_last_died(capsys: pytest.CaptureFixture[str]) -> None:
    """A Ready pod whose container died mid-exec reads exactly like an import
    error unless the pod's own record is read back. Measured on staging
    (2026-09-28): the chosen pod was Ready, the exec was terminated, and the
    retry then found no Ready pod at all."""
    pod = _pod(READY)
    pod["status"]["containerStatuses"] = [
        {"name": "n8n", "restartCount": 1, "lastState": {"terminated": {"reason": "OOMKilled", "exitCode": 137}}}
    ]
    kubectl = _Kubectl([pod], fail="multi-forge-sync")
    assert _import(kubectl) is False
    out = " ".join(capsys.readouterr().out.split())
    assert "restarts=1" in out
    assert "OOMKilled" in out


def test_an_unreadable_pod_list_is_not_reported_as_no_ready_pod(capsys: pytest.CaptureFixture[str]) -> None:
    """An unreachable API server (homelab off, a stale kubeconfig, RBAC) is a
    different fault from an n8n with no Ready pod, and must not read like one."""

    class _Unreachable(_Kubectl):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd[1:3] == ["get", "pods"]:
                self.calls.append(cmd)
                raise subprocess.CalledProcessError(1, cmd, stderr="Unable to connect to the server")
            return super().__call__(cmd, **kwargs)

    kubectl = _Unreachable([])
    assert _import(kubectl) is False
    assert kubectl.of("exec") == []
    out = " ".join(capsys.readouterr().out.split())
    assert "Unable to connect to the server" in out
    assert "no Ready n8n pod" not in out
