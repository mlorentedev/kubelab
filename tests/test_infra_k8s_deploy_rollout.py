"""Tests for TOOL-021: `infra k8s deploy` must exit non-zero when the rollout fails.

Every other step (generate / dry-run / apply / bootstrap) raises `typer.Exit(1)`
on failure, but a non-zero `kubectl rollout status` only logged a warning and the
command exited **0** (`toolkit/cli/infra.py`). So `make deploy-k8s && <next>`
proceeded over CrashLooping pods, and an agent or CI step chaining on the exit
code could not tell a broken deploy from a good one (process audit finding P6).

These tests drive the command by direct call (it is heavily wired to cluster
collaborators, all mocked here) and pin the exit code on both paths.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer

from toolkit.cli import infra


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    """A stand-in for subprocess.CompletedProcess (only the fields the code reads)."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _patch_collaborators(mocker, run_side_effect):
    """Mock everything k8s_deploy touches except command.run (the unit under test)."""
    mocker.patch.object(infra, "validate_environment_config", return_value=SimpleNamespace())
    mocker.patch.object(infra, "confirm_dangerous_operation")
    mocker.patch.object(infra, "_get_kubeconfig", return_value="/kubeconfig")
    mocker.patch.object(infra, "_kubectl_cmd", return_value="kubectl")
    mocker.patch.object(infra, "_apply_cluster_bootstrap", return_value=True)
    mocker.patch.object(infra.Path, "exists", return_value=True)
    return mocker.patch.object(infra.command, "run", side_effect=run_side_effect)


class TestDeployRolloutExitCode:
    def test_rollout_failure_exits_nonzero(self, mocker) -> None:
        # dry-run OK, apply OK, rollout FAILS (progress deadline exceeded).
        run = _patch_collaborators(
            mocker,
            [
                _proc(0),  # dry-run
                _proc(0, stdout="deployment.apps/web configured"),  # apply
                _proc(1, stderr='deployment "web" exceeded its progress deadline'),  # rollout
            ],
        )
        with pytest.raises(typer.Exit) as exc:
            infra.k8s_deploy(env="staging", skip_generate=True)

        assert exc.value.exit_code == 1, "a failed rollout must exit non-zero, not warn-and-succeed"
        assert run.call_count == 3, "dry-run + apply + rollout should all have run"

    def test_rollout_success_exits_zero(self, mocker) -> None:
        run = _patch_collaborators(
            mocker,
            [_proc(0), _proc(0, stdout="deployment.apps/web configured"), _proc(0)],
        )
        # Happy path returns normally (no typer.Exit raised).
        assert infra.k8s_deploy(env="staging", skip_generate=True) is None
        assert run.call_count == 3
