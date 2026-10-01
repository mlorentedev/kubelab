"""Tests for restore_window — pause one env's auto-sync while a prod app's data is replaced (BACKUP-070, #1998).

kubectl is simulated at the argv boundary: `FakeKube` keeps an Application on
the hub and a Deployment with its pods on the spoke, and answers the argvs the
module builds. A merge patch is applied with RFC 7386 semantics, so a test can
assert what the object looks like afterwards, not only what was sent.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Optional

import pytest
import yaml

from toolkit.features.restore_window import (
    ANNOTATION,
    WindowError,
    WindowHeldError,
    close_window,
    declared_sync_policy,
    held_windows,
    open_window,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
APPLICATIONS = REPO_ROOT / "infra" / "k8s" / "argocd" / "applications"
HUB = "/tmp/hub-config"
SPOKE = "/tmp/spoke-config"


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386, which is what `kubectl patch --type merge` sends."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


class FakeKube:
    """One hub Application and one spoke Deployment, driven by the argvs the module builds."""

    def __init__(self, env: str = "staging", *, pods_linger: int = 1, sync_restores: bool = True) -> None:
        manifest = declared_sync_policy(APPLICATIONS, env)
        self.app: dict[str, Any] = {
            "metadata": {"name": f"kubelab-{env}", "resourceVersion": "100", "annotations": {}},
            "spec": {"source": {"targetRevision": "master"}, "syncPolicy": copy.deepcopy(manifest)},
            "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}},
        }
        self.replicas = 1
        self.ready = 1
        self.pods_linger = pods_linger  # polls a pod survives after a scale to zero
        self.sync_restores = sync_restores
        self.declared_replicas = 1
        self.calls: list[list[str]] = []
        self.patches: list[dict[str, Any]] = []
        self.conflicts_left = 0
        self.synced = False

    # --- argv router -------------------------------------------------------
    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(argv)
        verb = argv[argv.index("-n") + 2]
        kind = argv[argv.index("-n") + 3]
        if kind.startswith("application"):
            return self._application(verb, argv)
        if verb == "scale":
            self.replicas = int(next(a for a in argv if a.startswith("--replicas=")).split("=", 1)[1])
            return 0, "scaled", ""
        if kind == "deployment":
            return 0, json.dumps(self._deployment()), ""
        if kind == "pods":
            return 0, json.dumps({"items": self._pods()}), ""
        raise AssertionError(f"unexpected argv {argv}")

    def _application(self, verb: str, argv: list[str]) -> tuple[int, str, str]:
        if verb == "get" and argv[-2:] == ["-o", "json"] and "applications" in argv:
            return 0, json.dumps({"items": [self.app]}), ""
        if verb == "get":
            return 0, json.dumps(self.app), ""
        body = json.loads(argv[argv.index("-p") + 1])
        self.patches.append(body)
        rv = (body.get("metadata") or {}).get("resourceVersion")
        if self.conflicts_left:
            self.conflicts_left -= 1
            self._bump()
            return 1, "", "Error from server (Conflict): the object has been modified"
        if rv is not None and rv != self.app["metadata"]["resourceVersion"]:
            return 1, "", "Error from server (Conflict): the object has been modified"
        if "operation" in body:
            self.synced = True
            if self.sync_restores:
                self.replicas = self.declared_replicas
            return 0, json.dumps(self.app), ""
        self.app = merge_patch(self.app, {k: v for k, v in body.items()})
        self._bump()
        return 0, json.dumps(self.app), ""

    def _bump(self) -> None:
        self.app["metadata"]["resourceVersion"] = str(int(self.app["metadata"]["resourceVersion"]) + 1)

    def _deployment(self) -> dict[str, Any]:
        self.ready = self.replicas if self.replicas else 0
        return {
            "spec": {
                "replicas": self.replicas,
                "selector": {"matchLabels": {"app": "n8n"}},
                "template": {
                    "spec": {"volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "n8n-data"}}]}
                },
            },
            "status": {"readyReplicas": self.ready} if self.ready else {},
        }

    def _pods(self) -> list[dict[str, Any]]:
        if self.replicas == 0:
            if self.pods_linger <= 0:
                return []
            self.pods_linger -= 1
        return [
            {
                "metadata": {"name": "n8n-abc", "labels": {"app": "n8n"}},
                "spec": {"volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "n8n-data"}}]},
            }
        ]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _open(kube: FakeKube, clock: Optional[Clock] = None, **kw: Any) -> dict[str, Any]:
    clock = clock or Clock()
    return open_window(
        env="staging",
        deployment="n8n",
        hub_kubeconfig=HUB,
        spoke_kubeconfig=SPOKE,
        holder="tester@host",
        run=kube,
        sleep=clock.sleep,
        clock=clock,
        **kw,
    )


def _close(kube: FakeKube, clock: Optional[Clock] = None, **kw: Any) -> Optional[dict[str, Any]]:
    clock = clock or Clock()
    return close_window(
        env="staging",
        applications_dir=APPLICATIONS,
        hub_kubeconfig=HUB,
        spoke_kubeconfig=SPOKE,
        run=kube,
        sleep=clock.sleep,
        clock=clock,
        **kw,
    )


# --- AC4: the open patch ------------------------------------------------------


class TestOpenPatch:
    def test_one_merge_patch_pauses_sync_and_names_the_holder_under_the_reads_resource_version(self) -> None:
        kube = FakeKube()
        _open(kube)
        app_patches = [p for p in kube.patches if "operation" not in p]
        assert len(app_patches) == 1
        body = app_patches[0]
        assert body["metadata"]["resourceVersion"] == "100"
        assert body["spec"]["syncPolicy"]["automated"]["enabled"] is False
        holder = json.loads(body["metadata"]["annotations"][ANNOTATION])
        assert holder["deployment"] == "n8n" and holder["by"] == "tester@host" and holder["since"]

    def test_the_patch_targets_the_envs_application_on_the_hub(self) -> None:
        kube = FakeKube()
        _open(kube)
        patch = next(c for c in kube.calls if "patch" in c)
        assert patch[:5] == ["kubectl", "--kubeconfig", HUB, "-n", "argocd"]
        assert patch[5:8] == ["patch", "application", "kubelab-staging"]
        assert patch[patch.index("--type") + 1] == "merge"

    def test_the_open_returns_the_policy_it_replaced(self) -> None:
        kube = FakeKube()
        replaced = _open(kube)
        assert replaced == declared_sync_policy(APPLICATIONS, "staging")

    def test_a_conflict_is_retried_once_on_a_fresh_read(self) -> None:
        kube = FakeKube()
        kube.conflicts_left = 1
        _open(kube)
        assert [p["metadata"]["resourceVersion"] for p in kube.patches if "operation" not in p] == ["100", "101"]

    def test_two_conflicts_in_a_row_fail_and_scale_nothing(self) -> None:
        kube = FakeKube()
        kube.conflicts_left = 2
        with pytest.raises(WindowError, match="(?i)conflict"):
            _open(kube)
        assert kube.replicas == 1
        assert not any("scale" in c for c in kube.calls)

    def test_an_application_without_automated_sync_is_refused(self) -> None:
        kube = FakeKube()
        kube.app["spec"]["syncPolicy"].pop("automated")
        with pytest.raises(WindowError, match="automated"):
            _open(kube)
        assert kube.patches == []


# --- AC2: a held window -------------------------------------------------------


class TestHeldWindow:
    def test_a_second_open_names_the_holder_and_patches_nothing(self) -> None:
        kube = FakeKube()
        kube.app["metadata"]["annotations"][ANNOTATION] = json.dumps(
            {"deployment": "authelia", "by": "other@lane", "since": "2026-10-01T20:00:00Z"}
        )
        with pytest.raises(WindowHeldError, match="other@lane") as exc:
            _open(kube)
        assert "authelia" in str(exc.value)
        assert kube.patches == []
        assert not any("scale" in c for c in kube.calls)

    def test_held_windows_lists_every_annotated_application(self) -> None:
        kube = FakeKube()
        assert held_windows(HUB, run=kube) == []
        kube.app["metadata"]["annotations"][ANNOTATION] = json.dumps({"deployment": "n8n", "by": "a@b", "since": "t"})
        held = held_windows(HUB, run=kube)
        assert len(held) == 1 and held[0][0] == "kubelab-staging" and "a@b" in held[0][1]


# --- AC1: scale and wait ------------------------------------------------------


class TestScaleAndWait:
    def test_the_deployment_is_scaled_to_zero_on_the_spoke(self) -> None:
        kube = FakeKube()
        _open(kube)
        scale = next(c for c in kube.calls if "scale" in c)
        assert scale[:5] == ["kubectl", "--kubeconfig", SPOKE, "-n", "kubelab"]
        assert "deployment/n8n" in scale and "--replicas=0" in scale
        assert kube.replicas == 0

    def test_the_open_returns_only_once_no_pod_mounts_the_claims(self) -> None:
        kube = FakeKube(pods_linger=3)
        _open(kube)
        assert kube.pods_linger == 0

    def test_a_pod_that_never_goes_fails_and_says_the_window_stays_open(self) -> None:
        kube = FakeKube(pods_linger=10_000)
        with pytest.raises(WindowError, match="(?i)window stays open"):
            _open(kube, timeout=30)
        assert ANNOTATION in kube.app["metadata"]["annotations"]

    def test_a_pod_from_another_owner_mounting_the_claim_still_blocks(self) -> None:
        kube = FakeKube(pods_linger=0)
        original = kube._pods

        def stray() -> list[dict[str, Any]]:
            pods = original()
            if not pods and kube.pods_linger > -2:
                kube.pods_linger -= 1
                return [
                    {
                        "metadata": {"name": "debug-shell", "labels": {"run": "debug"}},
                        "spec": {"volumes": [{"persistentVolumeClaim": {"claimName": "n8n-data"}}]},
                    }
                ]
            return pods

        kube._pods = stray  # type: ignore[method-assign]
        _open(kube)
        assert kube.pods_linger == -2


# --- AC3: the close -----------------------------------------------------------


class TestClose:
    @pytest.mark.parametrize("env", ["staging", "prod"])
    def test_the_restored_policy_is_exactly_gits(self, env: str) -> None:
        kube = FakeKube(env=env)
        open_window(
            env=env,
            deployment="n8n",
            hub_kubeconfig=HUB,
            spoke_kubeconfig=SPOKE,
            holder="t@h",
            run=kube,
            sleep=Clock().sleep,
            clock=Clock(),
        )
        kube.app["spec"]["syncPolicy"]["automated"]["allowEmpty"] = True  # drift a hand edit could add
        close_window(
            env=env,
            applications_dir=APPLICATIONS,
            hub_kubeconfig=HUB,
            spoke_kubeconfig=SPOKE,
            run=kube,
            sleep=Clock().sleep,
            clock=Clock(),
        )
        assert kube.app["spec"]["syncPolicy"] == declared_sync_policy(APPLICATIONS, env)
        assert ANNOTATION not in kube.app["metadata"]["annotations"]

    def test_the_close_patch_carries_the_reads_resource_version(self) -> None:
        kube = FakeKube()
        _open(kube)
        rv = kube.app["metadata"]["resourceVersion"]
        _close(kube)
        close_patch = [p for p in kube.patches if "operation" not in p][-1]
        assert close_patch["metadata"]["resourceVersion"] == rv

    def test_the_close_returns_the_policy_it_replaced(self) -> None:
        kube = FakeKube()
        _open(kube)
        replaced = _close(kube)
        assert replaced is not None and replaced["automated"]["enabled"] is False

    def test_the_close_triggers_one_sync_at_the_applications_revision(self) -> None:
        kube = FakeKube()
        kube.app["spec"]["source"]["targetRevision"] = "feat/preview"
        _open(kube)
        _close(kube)
        syncs = [p for p in kube.patches if "operation" in p]
        assert len(syncs) == 1
        assert syncs[0]["operation"]["sync"]["revision"] == "feat/preview"
        assert kube.replicas == 1

    def test_a_sync_that_never_restores_the_replicas_fails_with_what_it_saw(self) -> None:
        kube = FakeKube(sync_restores=False)
        _open(kube)
        with pytest.raises(WindowError, match="0/0|replicas"):
            _close(kube, timeout=30)

    def test_an_unhealthy_application_fails_the_close(self) -> None:
        kube = FakeKube()
        _open(kube)
        kube.app["status"]["health"]["status"] = "Degraded"
        with pytest.raises(WindowError, match="Degraded"):
            _close(kube, timeout=30)

    def test_closing_with_no_window_open_is_a_no_op(self) -> None:
        kube = FakeKube()
        assert _close(kube) is None
        assert kube.patches == []


def test_declared_sync_policy_reads_the_manifest_deploy_apps_applies() -> None:
    for env in ("staging", "prod"):
        docs = [d for d in yaml.safe_load_all((APPLICATIONS / f"{env}.yaml").read_text()) if d]
        app = next(d for d in docs if d.get("kind") == "Application")
        assert declared_sync_policy(APPLICATIONS, env) == app["spec"]["syncPolicy"]
