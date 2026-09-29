"""Tests for argo_manager — toolkit infra argo set-revision."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from toolkit.features.argo_manager import (
    ApplicationNotFoundError,
    DriftCheckResult,
    HubUnreachableError,
    SetRevisionResult,
    check_drift,
    set_revision,
)


def _mock_kubectl(*outputs: str) -> MagicMock:
    """Build a subprocess.run mock that returns each output in order, exit 0."""
    completed = [MagicMock(stdout=o, stderr="", returncode=0) for o in outputs]
    m = MagicMock(side_effect=completed)
    return m


class TestSetRevisionHappyPath:
    def test_returns_old_and_new_revision(self) -> None:
        before = json.dumps(
            {
                "spec": {"source": {"targetRevision": "fix/dash-ui-cosmetic"}},
                "status": {"sync": {"status": "Synced"}},
            }
        )
        after = json.dumps(
            {
                "spec": {"source": {"targetRevision": "master"}},
                "status": {"sync": {"status": "OutOfSync"}},
            }
        )
        with patch("toolkit.features.argo_manager.subprocess.run", _mock_kubectl(before, after)) as run:
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
        before = json.dumps(
            {
                "spec": {"source": {"targetRevision": "old-branch"}},
                "status": {"sync": {"status": "Synced"}},
            }
        )
        after = json.dumps(
            {
                "spec": {"source": {"targetRevision": "master"}},
                "status": {"sync": {"status": "Synced"}},
            }
        )
        with patch("toolkit.features.argo_manager.subprocess.run", _mock_kubectl(before, after)) as run:
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
        before = json.dumps(
            {
                "spec": {"source": {"targetRevision": "master"}},
                "status": {"sync": {"status": "Synced"}},
            }
        )
        after = json.dumps(
            {
                "spec": {"source": {"targetRevision": "y"}},
                "status": {"sync": {"status": "Synced"}},
            }
        )
        with patch("toolkit.features.argo_manager.subprocess.run", _mock_kubectl(before, after)) as run:
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
            1,
            ["kubectl"],
            output="",
            stderr='Error from server (NotFound): applications.argoproj.io "ghost" not found',
        )
        with patch("toolkit.features.argo_manager.subprocess.run", MagicMock(side_effect=err)):
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
        with patch("toolkit.cli.infra.argo_set_revision_feature", MagicMock(return_value=fake_result)) as feature:
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
        with patch(
            "toolkit.cli.infra.argo_set_revision_feature",
            MagicMock(side_effect=ApplicationNotFoundError("Application 'ghost' not found in namespace argocd")),
        ):
            result = runner.invoke(app, ["argo", "set-revision", "--app", "ghost", "--rev", "master"])

        assert result.exit_code != 0
        assert "ghost" in result.stdout
        assert "not found" in result.stdout.lower()

    def test_missing_required_args_exits_nonzero(self) -> None:
        from typer.testing import CliRunner

        from toolkit.cli.infra import app

        runner = CliRunner()
        result = runner.invoke(app, ["argo", "set-revision"])
        assert result.exit_code != 0


# ── check_drift (#1016) ────────────────────────────────────────────────────


def _diff_run(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """subprocess.run mock for a single `kubectl diff` invocation."""
    return MagicMock(return_value=MagicMock(returncode=returncode, stdout=stdout, stderr=stderr))


class TestCheckDrift:
    def test_exit_0_is_clean(self) -> None:
        with patch("toolkit.features.argo_manager.subprocess.run", _diff_run(0)):
            result = check_drift(applications_dir="infra/k8s/argocd/applications", kubeconfig="/tmp/kc")
        assert result == DriftCheckResult(clean=True, diff="")

    def test_exit_1_is_drift_with_diff_captured(self) -> None:
        diff_text = "-      selfHeal: true\n+      selfHeal: false\n"
        with patch("toolkit.features.argo_manager.subprocess.run", _diff_run(1, stdout=diff_text)):
            result = check_drift(applications_dir="infra/k8s/argocd/applications", kubeconfig="/tmp/kc")
        assert result.clean is False
        assert result.diff == diff_text

    def test_exit_2_raises_hub_unreachable_not_reported_clean(self) -> None:
        # This is the failure #1016 itself taught: a check that cannot run must
        # never be silently treated as "no drift found".
        with patch(
            "toolkit.features.argo_manager.subprocess.run",
            _diff_run(2, stderr="dial tcp 100.64.0.7:6443: i/o timeout"),
        ):
            with pytest.raises(HubUnreachableError) as exc:
                check_drift(applications_dir="infra/k8s/argocd/applications", kubeconfig="/tmp/kc")
        assert "i/o timeout" in str(exc.value)

    def test_uses_provided_dir_and_kubeconfig(self) -> None:
        with patch("toolkit.features.argo_manager.subprocess.run", _diff_run(0)) as run:
            check_drift(applications_dir="some/dir", kubeconfig="/path/kc")
        argv = run.call_args.args[0]
        assert "diff" in argv
        assert "some/dir" in argv
        assert "/path/kc" in argv


class TestArgoCheckDriftCLI:
    def test_clean_exits_0(self) -> None:
        from typer.testing import CliRunner

        from toolkit.cli.infra import app

        runner = CliRunner()
        with patch(
            "toolkit.cli.infra.argo_check_drift_feature",
            MagicMock(return_value=DriftCheckResult(clean=True, diff="")),
        ):
            result = runner.invoke(app, ["argo", "check-drift"])
        assert result.exit_code == 0, result.stdout
        assert "no drift" in result.stdout.lower()

    def test_drift_found_exits_1_and_prints_diff(self) -> None:
        from typer.testing import CliRunner

        from toolkit.cli.infra import app

        runner = CliRunner()
        with patch(
            "toolkit.cli.infra.argo_check_drift_feature",
            MagicMock(return_value=DriftCheckResult(clean=False, diff="selfHeal: true vs false")),
        ):
            result = runner.invoke(app, ["argo", "check-drift"])
        assert result.exit_code == 1
        assert "selfHeal" in result.stdout
        assert "deploy-apps" in result.stdout

    def test_hub_unreachable_exits_2_not_0(self) -> None:
        from typer.testing import CliRunner

        from toolkit.cli.infra import app

        runner = CliRunner()
        with patch(
            "toolkit.cli.infra.argo_check_drift_feature",
            MagicMock(side_effect=HubUnreachableError("i/o timeout")),
        ):
            result = runner.invoke(app, ["argo", "check-drift"])
        assert result.exit_code == 2, "hub-unreachable must be distinguishable from both clean(0) and drift(1)"
        assert "cannot check" in result.stdout.lower()


def _app_on(revision: str) -> str:
    return json.dumps({"spec": {"source": {"targetRevision": revision}}, "status": {"sync": {"status": "Synced"}}})


class TestSetRevisionRefusesAnApplicationAnotherLaneHolds:
    """#1083: repointing staging while another branch holds it clobbers that lane's preview.

    Measured 2026-09-25: staging was on `fix/grafana-oauth-single-door`, OPS-023
    repointed it at its own branch, and the old value was printed only after the
    patch. Argo CD rolled Grafana to the wrong config within seconds.
    """

    def test_a_feature_branch_does_not_replace_another_feature_branch(self) -> None:
        from toolkit.features.argo_manager import RevisionHeldError

        with patch("toolkit.features.argo_manager.subprocess.run", _mock_kubectl(_app_on("fix/other-lane"))) as run:
            with pytest.raises(RevisionHeldError, match="fix/other-lane"):
                set_revision(app="kubelab-staging", rev="feat/mine", kubeconfig="/tmp/kc")

        # Refused before the patch: only the read ran.
        assert run.call_count == 1

    def test_force_replaces_it(self) -> None:
        with patch(
            "toolkit.features.argo_manager.subprocess.run",
            _mock_kubectl(_app_on("fix/other-lane"), _app_on("feat/mine")),
        ) as run:
            result = set_revision(app="kubelab-staging", rev="feat/mine", kubeconfig="/tmp/kc", force=True)

        assert result.old_revision == "fix/other-lane"
        assert run.call_count == 2

    @pytest.mark.parametrize(
        ("current", "requested"),
        [
            ("master", "feat/mine"),  # taking an idle staging
            ("feat/mine", "feat/mine"),  # re-running your own
            ("feat/mine", "master"),  # patch-back: master is the release
        ],
    )
    def test_the_unheld_cases_need_no_force(self, current: str, requested: str) -> None:
        with patch(
            "toolkit.features.argo_manager.subprocess.run",
            _mock_kubectl(_app_on(current), _app_on(requested)),
        ) as run:
            set_revision(app="kubelab-staging", rev=requested, kubeconfig="/tmp/kc")

        assert run.call_count == 2


class TestSetRevisionPatchesOnlyTheRevisionItRead:
    """The guard reads, then patches: without a precondition, two lanes that both
    read `master` in the same second both pass, and the second silently replaces
    the first. The read's resourceVersion makes the second patch a 409 instead
    (pr-agent on #1893)."""

    def _app(self, revision: str, resource_version: str) -> str:
        return json.dumps(
            {
                "metadata": {"resourceVersion": resource_version},
                "spec": {"source": {"targetRevision": revision}},
                "status": {"sync": {"status": "Synced"}},
            }
        )

    def test_the_patch_carries_the_resource_version_it_read(self) -> None:
        with patch(
            "toolkit.features.argo_manager.subprocess.run",
            _mock_kubectl(self._app("master", "4711"), self._app("feat/mine", "4712")),
        ) as run:
            set_revision(app="kubelab-staging", rev="feat/mine", kubeconfig="/tmp/kc")

        patch_argv = run.call_args_list[1].args[0]
        payload = json.loads(patch_argv[patch_argv.index("-p") + 1])
        assert payload["metadata"]["resourceVersion"] == "4711"
        assert payload["spec"]["source"]["targetRevision"] == "feat/mine"

    @staticmethod
    def _conflict() -> Exception:
        import subprocess

        return subprocess.CalledProcessError(
            1,
            ["kubectl"],
            stderr='Error from server (Conflict): Operation cannot be fulfilled on applications.argoproj.io '
            '"kubelab-staging": the object has been modified; please apply your changes to the latest version',
        )

    def _read(self, revision: str, resource_version: str) -> MagicMock:
        return MagicMock(stdout=self._app(revision, resource_version), stderr="", returncode=0)

    def test_a_lane_that_repointed_it_in_between_is_named_as_the_holder(self) -> None:
        from toolkit.features.argo_manager import RevisionHeldError

        steps = [self._read("master", "4711"), self._conflict(), self._read("fix/other-lane", "4712")]
        with patch("toolkit.features.argo_manager.subprocess.run", MagicMock(side_effect=steps)) as run:
            with pytest.raises(RevisionHeldError, match="fix/other-lane"):
                set_revision(app="kubelab-staging", rev="feat/mine", kubeconfig="/tmp/kc")

        # Re-read, refused by the guard: no second patch.
        assert run.call_count == 3

    def test_a_status_write_in_between_is_not_blamed_on_a_lane(self) -> None:
        """Argo CD's controller writes `status` on every refresh, which bumps the
        resourceVersion without touching targetRevision (pr-agent on #1893)."""
        steps = [
            self._read("master", "4711"),
            self._conflict(),
            self._read("master", "4712"),
            self._read("feat/mine", "4713"),
        ]
        with patch("toolkit.features.argo_manager.subprocess.run", MagicMock(side_effect=steps)) as run:
            result = set_revision(app="kubelab-staging", rev="feat/mine", kubeconfig="/tmp/kc")

        assert result.old_revision == "master"
        assert result.new_revision == "feat/mine"
        retry = run.call_args_list[3].args[0]
        assert json.loads(retry[retry.index("-p") + 1])["metadata"]["resourceVersion"] == "4712"

    def test_it_gives_up_after_one_retry(self) -> None:
        import subprocess

        steps = [self._read("master", "4711"), self._conflict(), self._read("master", "4712"), self._conflict()]
        with patch("toolkit.features.argo_manager.subprocess.run", MagicMock(side_effect=steps)):
            with pytest.raises(subprocess.CalledProcessError):
                set_revision(app="kubelab-staging", rev="feat/mine", kubeconfig="/tmp/kc")


@pytest.mark.parametrize(("force", "expected"), [("", False), ("0", False), ("1", True)])
def test_only_force_1_forces(force: str, expected: bool) -> None:
    """`$(if $(FORCE),...)` tests emptiness, so FORCE=0 used to force (pr-agent on #1893)."""
    import pathlib
    import subprocess

    repo = pathlib.Path(__file__).resolve().parent.parent
    out = subprocess.run(
        ["make", "-n", "-C", str(repo), "argo-set-revision", "APP=kubelab-staging", "REV=feat/mine", f"FORCE={force}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    line = next(ln for ln in out.splitlines() if "--app" in ln)
    assert ("--force" in line) is expected, line
