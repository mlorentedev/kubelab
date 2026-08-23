"""Tests for the hub pause/resume primitive (GCP-001 Phase 5 handover).

The pause is what makes a hub handover reversible: `unregister-spoke` enforces
the single-writer invariant by deleting the retiring hub's credential, which
also destroys the rollback. These assert the two properties that make pausing
trustworthy enough to hand prod over on:

1. It removes NOTHING. A pause that deletes is an unregister wearing the wrong
   name, and the rollback it promises does not exist.
2. "Paused" means no controller pod remains -- not that a scale command exited 0.

Pure planning and the wait loop are covered without a cluster; `_kubectl` is the
only side effect and is stubbed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.features import hub_pause as hp
from toolkit.features.hub_pause import (
    CONTROLLER_KIND,
    CONTROLLER_NAME,
    plan,
    set_hub_paused,
    wait_for_pods,
)

_HUB = Path("/tmp/kubelab-hub-aws-config")


class TestPlan:
    """The plan is one scale action, and it is the whole plan."""

    def test_pause_scales_the_controller_to_zero(self) -> None:
        (step,) = plan(_HUB, 0)
        assert "--replicas=0" in step.argv
        assert CONTROLLER_NAME in step.argv

    def test_resume_scales_it_back_to_one(self) -> None:
        (step,) = plan(_HUB, 1)
        assert "--replicas=1" in step.argv

    def test_targets_a_statefulset_not_a_deployment(self) -> None:
        # Argo CD ships the application-controller as a StatefulSet. `kubectl scale
        # deploy` matches nothing here and still exits 0 on some paths -- it would
        # report a pause while the hub kept writing.
        (step,) = plan(_HUB, 0)
        assert CONTROLLER_KIND == "statefulset"
        assert "statefulset" in step.argv
        assert "deploy" not in step.argv and "deployment" not in step.argv

    def test_names_the_hub_explicitly(self) -> None:
        # Two hubs are live during the migration; an implicit hub is the defect.
        (step,) = plan(_HUB, 0)
        assert "--kubeconfig" in step.argv
        assert str(_HUB) in step.argv

    def test_deletes_nothing(self) -> None:
        # THE load-bearing assertion. The pause is the rollback window; a plan that
        # deletes anything has silently become an unregister.
        for replicas in (0, 1):
            for step in plan(_HUB, replicas):
                assert "delete" not in step.argv
                assert "patch" not in step.argv


class TestWaitForPods:
    """`paused` is a fact about pods, never about what the API server was told."""

    def test_returns_once_the_pods_are_gone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = iter([["argocd-application-controller-0"], []])
        monkeypatch.setattr(hp, "controller_pods", lambda _: next(calls))
        monkeypatch.setattr(hp.time, "sleep", lambda _: None)
        assert wait_for_pods(_HUB, expected_gone=True) == []

    def test_raises_when_the_pod_outlives_the_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The false-green this whole primitive exists to refuse: replicas=0 accepted,
        # controller still running, cutover proceeds on an assumption that is untrue.
        monkeypatch.setattr(hp, "controller_pods", lambda _: ["argocd-application-controller-0"])
        monkeypatch.setattr(hp.time, "sleep", lambda _: None)
        with pytest.raises(RuntimeError, match="did not take"):
            wait_for_pods(_HUB, expected_gone=True, timeout_s=0.05)

    def test_resume_waits_for_the_pod_to_appear(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = iter([[], ["argocd-application-controller-0"]])
        monkeypatch.setattr(hp, "controller_pods", lambda _: next(calls))
        monkeypatch.setattr(hp.time, "sleep", lambda _: None)
        assert wait_for_pods(_HUB, expected_gone=False) == ["argocd-application-controller-0"]

    def test_resume_raises_when_no_pod_ever_comes_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A failed resume leaves the spoke with NO writer, which looks exactly like
        # a healthy paused hub. Silence here is the worst outcome of the four.
        monkeypatch.setattr(hp, "controller_pods", lambda _: [])
        monkeypatch.setattr(hp.time, "sleep", lambda _: None)
        with pytest.raises(RuntimeError, match="did not take"):
            wait_for_pods(_HUB, expected_gone=False, timeout_s=0.05)


class TestSetHubPaused:
    """Execution: dry-run changes nothing, a failed scale is never reported as a pause."""

    def test_dry_run_runs_no_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(_argv: list[str]) -> tuple[int, str]:
            raise AssertionError("dry-run must not execute anything")

        monkeypatch.setattr(hp, "_kubectl", _boom)
        steps = set_hub_paused(_HUB, paused=True, dry_run=True)
        assert len(steps) == 1

    def test_a_failed_scale_raises_rather_than_claiming_a_pause(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hp, "_kubectl", lambda _argv: (1, "Error from server (Forbidden)"))
        with pytest.raises(RuntimeError, match="step failed"):
            set_hub_paused(_HUB, paused=True)

    def test_wait_is_reached_on_a_successful_scale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hp, "_kubectl", lambda _argv: (0, ""))
        monkeypatch.setattr(hp, "controller_pods", lambda _: [])
        set_hub_paused(_HUB, paused=True)  # no raise == the wait observed pod absence

    def test_wait_false_skips_the_observation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Available for tests and dry composition, never for a cutover step.
        monkeypatch.setattr(hp, "_kubectl", lambda _argv: (0, ""))

        def _boom(_hub: Path) -> list[str]:
            raise AssertionError("wait=False must not poll")

        monkeypatch.setattr(hp, "controller_pods", _boom)
        set_hub_paused(_HUB, paused=True, wait=False)
