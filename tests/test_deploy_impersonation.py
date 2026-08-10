"""TOOL-029: `k8s deploy` must apply as the identity that delivers to prod.

`make deploy-k8s` runs with the operator's unrestricted kubeconfig; Argo CD
delivers as a least-privilege ServiceAccount (ADR-041). Those are different
actors, so a manifest the operator can apply is not necessarily one Argo CD can.
IDP-031 shipped a `LimitRange` that passed lint, render, the infra tests and a
full staging deploy, and was then refused in prod (#948) — the GitOps path is
only exercised *after* merge, so nothing before it could have known.

Impersonating the spoke makes the manual path incapable of succeeding where the
GitOps path would fail. These tests pin that the flag reaches both the dry-run
and the real apply, that the identity is read from the RBAC manifest rather than
duplicated, and that the escape hatch is opt-in and announces itself.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from toolkit.cli import infra

SPOKE_SA = "--as=system:serviceaccount:kubelab:argocd-manager"


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _run_deploy(mocker, monkeypatch) -> list[str]:
    """Drive k8s_deploy with every cluster collaborator mocked; return the commands it ran."""
    mocker.patch.object(infra, "validate_environment_config", return_value=SimpleNamespace())
    mocker.patch.object(infra, "confirm_dangerous_operation")
    mocker.patch.object(infra, "_get_kubeconfig", return_value="/kubeconfig")
    mocker.patch.object(infra, "_kubectl_cmd", return_value="kubectl")
    mocker.patch.object(infra, "_apply_cluster_bootstrap", return_value=True)
    mocker.patch.object(infra.Path, "exists", return_value=True)
    run = mocker.patch.object(infra.command, "run", side_effect=[_proc(0), _proc(0), _proc(0)])

    infra.k8s_deploy(env="staging", skip_generate=True)
    return [call.args[0] for call in run.call_args_list]


class TestSpokeServiceAccountResolution:
    """The impersonated identity comes from the manifest, not from a constant."""

    def test_resolves_from_the_rbac_manifest(self) -> None:
        assert infra._spoke_service_account() == "system:serviceaccount:kubelab:argocd-manager"

    def test_manifest_is_the_single_source(self, tmp_path, monkeypatch) -> None:
        """Renaming the ServiceAccount must move the impersonated identity with it.

        If this ever fails, the toolkit has started duplicating an identity the
        manifest owns — which is the drift this whole ticket exists to prevent.
        """
        manifest = tmp_path / infra.SPOKE_RBAC_MANIFEST
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n"
            "  name: renamed-manager\n  namespace: elsewhere\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(infra.settings, "project_root", tmp_path)

        assert infra._spoke_service_account() == "system:serviceaccount:elsewhere:renamed-manager"

    def test_missing_service_account_fails_loudly(self, tmp_path, monkeypatch) -> None:
        """A manifest with no ServiceAccount must raise, never return a default.

        Falling back to a hardcoded name here would silently restore the exact
        divergence this guards against.
        """
        manifest = tmp_path / infra.SPOKE_RBAC_MANIFEST
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: nope\n", encoding="utf-8")
        monkeypatch.setattr(infra.settings, "project_root", tmp_path)

        with pytest.raises(ValueError, match="No ServiceAccount found"):
            infra._spoke_service_account()


class TestImpersonationFlag:
    """Impersonation is the default; opting out is explicit and loud."""

    def test_impersonates_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv(infra.DEPLOY_AS_OPERATOR_ENV, raising=False)
        assert infra._impersonation_flag() == "--as=system:serviceaccount:kubelab:argocd-manager"

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " 1 "])
    def test_escape_hatch_opts_out(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv(infra.DEPLOY_AS_OPERATOR_ENV, value)
        assert infra._impersonation_flag() == ""

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "maybe"])
    def test_anything_else_still_impersonates(self, monkeypatch, value: str) -> None:
        """Fail closed: only an explicit affirmative drops the safeguard."""
        monkeypatch.setenv(infra.DEPLOY_AS_OPERATOR_ENV, value)
        assert infra._impersonation_flag().startswith("--as=")

    def test_escape_hatch_warns(self, monkeypatch, mocker) -> None:
        """Elevated privilege must be visible in the output, not merely permitted."""
        warn = mocker.patch.object(infra.logger, "warning")
        monkeypatch.setenv(infra.DEPLOY_AS_OPERATOR_ENV, "1")

        infra._impersonation_flag()

        assert warn.call_count == 1
        message = warn.call_args[0][0]
        assert infra.DEPLOY_AS_OPERATOR_ENV in message
        assert "TOOL-029" in message


class TestDeployUsesImpersonation:
    """The flag must reach the commands — a helper returning it is not enough."""

    def test_dry_run_and_apply_both_impersonate(self, mocker, monkeypatch) -> None:
        monkeypatch.delenv(infra.DEPLOY_AS_OPERATOR_ENV, raising=False)

        commands = _run_deploy(mocker, monkeypatch)

        dry_run, apply_cmd = commands[0], commands[1]
        assert "--dry-run=server" in dry_run, "sanity: first call should be the dry-run"
        assert SPOKE_SA in dry_run, (
            "the dry-run must impersonate the spoke — this is where a prod refusal "
            "gets turned into a local failure, before anything is mutated"
        )
        assert SPOKE_SA in apply_cmd, "the real apply must impersonate too, not just the dry-run"

    def test_escape_hatch_removes_it_from_both(self, mocker, monkeypatch) -> None:
        monkeypatch.setenv(infra.DEPLOY_AS_OPERATOR_ENV, "1")

        commands = _run_deploy(mocker, monkeypatch)

        assert not any("--as=" in c for c in commands), (
            "with the escape hatch set, no command may impersonate"
        )

    def test_rollout_status_is_not_impersonated(self, mocker, monkeypatch) -> None:
        """Reads stay as the operator: the spoke's read grants are wildcarded, but
        narrowing an unrelated read to the SA would couple diagnosis to delivery."""
        monkeypatch.delenv(infra.DEPLOY_AS_OPERATOR_ENV, raising=False)

        commands = _run_deploy(mocker, monkeypatch)

        rollout = commands[2]
        assert "rollout status" in rollout, "sanity: third call should be the rollout wait"
        assert "--as=" not in rollout
