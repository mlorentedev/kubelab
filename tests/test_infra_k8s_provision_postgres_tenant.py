"""Tests for `infra k8s provision-postgres-tenant`'s failure and kubeconfig handling.

Two defects, found live against prod (TOOL-050 follow-up): the `kubectl exec`
had no `--kubeconfig`, so it silently ran against whatever cluster the ambient
shell context pointed at instead of the target `--env`; and a non-zero
`psql`/`kubectl exec` only logged a warning and returned exit 0, so
`make deploy-k8s ENV=prod` reported success while the tenant was never
provisioned. Same failure class as TOOL-021 (`k8s_deploy` rollout).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer

from toolkit.cli import infra


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _patch_collaborators(mocker, run_return):
    mocker.patch.object(infra, "_get_kubeconfig", return_value="/kubeconfig-prod")
    cfg = mocker.Mock()
    cfg.get_secret_by_path.return_value = "db-password"
    mocker.patch("toolkit.features.configuration.ConfigurationManager", return_value=cfg)
    return mocker.patch("subprocess.run", return_value=run_return)


class TestProvisionPostgresTenantExitCode:
    def test_provisioning_failure_exits_nonzero(self, mocker) -> None:
        _patch_collaborators(mocker, _proc(1, stderr="connection refused"))

        with pytest.raises(typer.Exit) as exc:
            infra.k8s_provision_postgres_tenant(env="prod", tenant="vikunja", dry_run=False)

        assert exc.value.exit_code == 1, "a failed provisioning exec must exit non-zero, not warn-and-succeed"

    def test_provisioning_success_exits_zero(self, mocker) -> None:
        _patch_collaborators(mocker, _proc(0))

        assert infra.k8s_provision_postgres_tenant(env="prod", tenant="vikunja", dry_run=False) is None

    def test_kubectl_exec_targets_the_env_specific_kubeconfig(self, mocker) -> None:
        run = _patch_collaborators(mocker, _proc(0))

        infra.k8s_provision_postgres_tenant(env="prod", tenant="vikunja", dry_run=False)

        cmd = run.call_args.args[0]
        assert "--kubeconfig" in cmd, "must not fall back to the ambient default kubectl context"
        assert cmd[cmd.index("--kubeconfig") + 1] == "/kubeconfig-prod"
