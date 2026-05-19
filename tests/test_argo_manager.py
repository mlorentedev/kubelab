"""Tests for argo_manager — toolkit infra argo set-revision."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from toolkit.features.argo_manager import (
    ApplicationNotFoundError,
    SetRevisionResult,
    set_revision,
)


def _mock_kubectl(*outputs: str) -> MagicMock:
    """Build a subprocess.run mock that returns each output in order, exit 0."""
    completed = [MagicMock(stdout=o, stderr="", returncode=0) for o in outputs]
    m = MagicMock(side_effect=completed)
    return m


class TestSetRevisionHappyPath:
    def test_returns_old_and_new_revision(self) -> None:
        before = json.dumps({
            "spec": {"source": {"targetRevision": "fix/dash-ui-cosmetic"}},
            "status": {"sync": {"status": "Synced"}},
        })
        after = json.dumps({
            "spec": {"source": {"targetRevision": "master"}},
            "status": {"sync": {"status": "OutOfSync"}},
        })
        with patch("toolkit.features.argo_manager.subprocess.run",
                   _mock_kubectl(before, after)) as run:
            result = set_revision(
                app="kubelab-staging",
                rev="master",
                kubeconfig="/tmp/kubeconfig-hub",
            )

        assert isinstance(result, SetRevisionResult)
        assert result.old_revision == "fix/dash-ui-cosmetic"
        assert result.new_revision == "master"
        assert result.sync_status == "OutOfSync"
        assert run.call_count == 2

    def test_patch_payload_is_strategic_merge(self) -> None:
        before = json.dumps({
            "spec": {"source": {"targetRevision": "old-branch"}},
            "status": {"sync": {"status": "Synced"}},
        })
        after = json.dumps({
            "spec": {"source": {"targetRevision": "master"}},
            "status": {"sync": {"status": "Synced"}},
        })
        with patch("toolkit.features.argo_manager.subprocess.run",
                   _mock_kubectl(before, after)) as run:
            set_revision(
                app="kubelab-staging",
                rev="master",
                kubeconfig="/tmp/kc",
            )

        patch_call = run.call_args_list[1]
        argv = patch_call.args[0]
        assert "patch" in argv
        assert "--type" in argv
        idx = argv.index("--type")
        assert argv[idx + 1] == "merge"
        payload_idx = argv.index("-p")
        payload = json.loads(argv[payload_idx + 1])
        assert payload == {"spec": {"source": {"targetRevision": "master"}}}

    def test_uses_provided_kubeconfig_and_namespace(self) -> None:
        before = json.dumps({
            "spec": {"source": {"targetRevision": "x"}},
            "status": {"sync": {"status": "Synced"}},
        })
        after = json.dumps({
            "spec": {"source": {"targetRevision": "y"}},
            "status": {"sync": {"status": "Synced"}},
        })
        with patch("toolkit.features.argo_manager.subprocess.run",
                   _mock_kubectl(before, after)) as run:
            set_revision(app="a", rev="y", kubeconfig="/path/kc", namespace="custom-ns")

        for call in run.call_args_list:
            argv = call.args[0]
            assert "--kubeconfig" in argv
            assert "/path/kc" in argv
            assert "-n" in argv
            assert "custom-ns" in argv


class TestSetRevisionErrors:
    def test_missing_application_raises(self) -> None:
        import subprocess
        err = subprocess.CalledProcessError(
            1, ["kubectl"], output="",
            stderr='Error from server (NotFound): applications.argoproj.io "ghost" not found',
        )
        with patch("toolkit.features.argo_manager.subprocess.run",
                   MagicMock(side_effect=err)):
            with pytest.raises(ApplicationNotFoundError) as exc:
                set_revision(app="ghost", rev="master", kubeconfig="/tmp/kc")
        assert "ghost" in str(exc.value)


class TestArgoSetRevisionCLI:
    def test_happy_path_prints_old_and_new(self) -> None:
        from typer.testing import CliRunner

        from toolkit.cli.infra import app

        runner = CliRunner()
        fake_result = SetRevisionResult(
            old_revision="fix/dash-ui-cosmetic",
            new_revision="master",
            sync_status="OutOfSync",
        )
        with patch("toolkit.cli.infra.argo_set_revision_feature",
                   MagicMock(return_value=fake_result)) as feature:
            result = runner.invoke(
                app,
                ["argo", "set-revision", "--app", "kubelab-staging", "--rev", "master"],
            )

        assert result.exit_code == 0, result.stdout
        assert "fix/dash-ui-cosmetic" in result.stdout
        assert "master" in result.stdout
        assert "OutOfSync" in result.stdout
        feature.assert_called_once()

    def test_missing_app_exits_nonzero(self) -> None:
        from typer.testing import CliRunner

        from toolkit.cli.infra import app

        runner = CliRunner()
        with patch("toolkit.cli.infra.argo_set_revision_feature",
                   MagicMock(side_effect=ApplicationNotFoundError(
                       "Application 'ghost' not found in namespace argocd"))):
            result = runner.invoke(
                app, ["argo", "set-revision", "--app", "ghost", "--rev", "master"]
            )

        assert result.exit_code != 0
        assert "ghost" in result.stdout
        assert "not found" in result.stdout.lower()

    def test_missing_required_args_exits_nonzero(self) -> None:
        from typer.testing import CliRunner

        from toolkit.cli.infra import app

        runner = CliRunner()
        result = runner.invoke(app, ["argo", "set-revision"])
        assert result.exit_code != 0
