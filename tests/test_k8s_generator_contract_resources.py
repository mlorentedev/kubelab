"""RES-HOST-001 slice C: the renderer turns a contract's `resources:` into cluster objects.

A product that claims a volume gets one PVC, and every pod of it mounts the claim; a job
claim becomes a CronJob that runs the product's own image. The claims are read from the
env's contract snapshot, never from values (D6: `_extract_app_env_vars` would flatten them
into pod environment variables). Each test renders the real templates from the context
`_build_context` builds and reads the objects a cluster would be handed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from toolkit.core.templating import create_renderer
from toolkit.features import generator_k8s, product_registry
from toolkit.features.generator_k8s import K8sGenerator
from toolkit.features.k8s_secrets import pull_secret_name

REPO = Path(__file__).resolve().parent.parent
HOST = "gitea.kubelab.live"

REGISTRY = f"""\
products:
  api:
    forge: in-tree
  sample:
    repository: personal/sample
    forge: gitea
    receiver: generic
    image_registry: {HOST}/personal
    private: true
    pull_credential: {{username: reviewer, secret: ghcr.pull_token}}
"""

CONTRACT = """\
schema_version: 1
image: gitea.kubelab.live/personal/sample
port: 8080
health_path: /healthz
hostnames:
  staging: sample.staging.kubelab.live
  prod: sample.kubelab.live
auth: forwardauth
resources:
  data:
    type: volume
    params: {{size: {size}, mount_path: /data{fs_group}}}
  daily:
    type: job
    params: {{schedule: "0 6 * * *", command: [sample, daily], volume: data, active_deadline_seconds: 900}}
"""


def _contract(size: str = "1Gi", fs_group: int | None = 10001) -> str:
    return CONTRACT.format(size=size, fs_group=f", fs_group: {fs_group}" if fs_group else "")


def _env(app: str) -> dict[str, str]:
    prefix = f"APPS_PLATFORM_{app.upper()}"
    return {
        f"{prefix}_IMAGE_NAME": f"kubelab-{app}",
        f"{prefix}_DOMAIN": f"{app}.example.test",
        f"{prefix}_DEFAULT_PORT": "8080",
        f"{prefix}_VERSION": "sha-1111111",
    }


@pytest.fixture
def snapshots(tmp_path: Path) -> Path:
    """The contract snapshot tree `_build_context` reads: staging flat, prod under `prod/`."""
    root = tmp_path / "contracts"
    (root / "prod").mkdir(parents=True)
    (root / "sample.yaml").write_text(_contract("1Gi"), encoding="utf-8")
    (root / "prod" / "sample.yaml").write_text(_contract("5Gi"), encoding="utf-8")
    return root


@pytest.fixture
def build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshots: Path):
    """`_build_context(env)` for `api` (no snapshot) and `sample` (a snapshot with a volume and a job)."""
    registry = tmp_path / "products.yaml"
    registry.write_text(REGISTRY, encoding="utf-8")
    monkeypatch.setattr(product_registry, "registry_path", lambda: registry)
    monkeypatch.setattr(K8sGenerator, "snapshot_dir", snapshots)
    monkeypatch.setattr(K8sGenerator, "_build_migrations", lambda self, env_vars: {})

    def run(env: str = "staging", secrets: bool = False) -> dict[str, Any]:
        manager = MagicMock()
        manager.return_value.get_env_vars.return_value = {
            "REGISTRY": "docker.io/mlorentedev",
            **_env("api"),
            **_env("sample"),
        }
        monkeypatch.setattr(generator_k8s, "ConfigurationManager", manager)
        monkeypatch.setattr(K8sGenerator, "_has_secret_vars", lambda self, component: secrets)
        return K8sGenerator()._build_context(env)

    return run


def _objects(context: dict[str, Any], tmp_path: Path) -> list[dict[str, Any]]:
    """Every object the generator's templates render from `context` (the migrations one needs the API's files)."""
    renderer = create_renderer(REPO / "infra/k8s/templates")
    out: list[dict[str, Any]] = []
    for template, name in K8sGenerator._TEMPLATE_MAP:
        if template == "migrations.yaml.j2":
            continue
        path = tmp_path / name
        assert renderer.render_template(template, path, context), template
        out += [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]
    return out


def _one(objects: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    found = [o for o in objects if o["kind"] == kind and o["metadata"]["name"] == name]
    assert len(found) == 1, f"{len(found)} {kind}/{name} among {[(o['kind'], o['metadata']['name']) for o in objects]}"
    return found[0]


class TestContext:
    def test_an_app_with_a_snapshot_carries_its_volumes_and_jobs(self, build) -> None:
        sample = next(a for a in build()["apps"] if a["name"] == "sample")

        (volume,) = sample["volumes"]
        assert (volume["name"], volume["claim"], volume["size"], volume["mount_path"], volume["fs_group"]) == (
            "data",
            "sample-data",
            "1Gi",
            "/data",
            10001,
        )
        (job,) = sample["jobs"]
        assert (job["name"], job["command"], job["active_deadline_seconds"]) == ("daily", ["sample", "daily"], 900)
        assert job["volume"]["claim"] == "sample-data"

    def test_an_app_without_a_snapshot_has_no_claims(self, build) -> None:
        api = next(a for a in build()["apps"] if a["name"] == "api")

        assert api["volumes"] == []
        assert api["jobs"] == []

    def test_each_env_reads_its_own_snapshot(self, build) -> None:
        sizes = {
            env: next(a for a in build(env)["apps"] if a["name"] == "sample")["volumes"][0]["size"]
            for env in ("staging", "prod")
        }

        assert sizes == {"staging": "1Gi", "prod": "5Gi"}

    def test_claims_never_reach_the_pod_environment(self, build, tmp_path: Path) -> None:
        """D6: the contract is not read through values, so nothing of it is flattened into the ConfigMap."""
        context = build()
        sample = next(a for a in context["apps"] if a["name"] == "sample")

        assert set(sample["env_vars"]) == {"ENVIRONMENT"}
        configmap = _one(_objects(context, tmp_path), "ConfigMap", "sample-config")
        assert configmap["data"] == {"ENVIRONMENT": "staging"}


class TestVolumeClaim:
    def test_renders_one_pvc_named_for_the_app_and_the_claim(self, build, tmp_path: Path) -> None:
        objects = _objects(build(), tmp_path)

        pvcs = [o for o in objects if o["kind"] == "PersistentVolumeClaim"]
        assert [p["metadata"]["name"] for p in pvcs] == ["sample-data"]
        pvc = pvcs[0]
        assert pvc["metadata"]["namespace"] == "kubelab"
        assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]
        assert pvc["spec"]["resources"]["requests"] == {"storage": "1Gi"}

    def test_leaves_the_storage_class_to_the_cluster_default(self, build, tmp_path: Path) -> None:
        pvc = _one(_objects(build(), tmp_path), "PersistentVolumeClaim", "sample-data")

        assert "storageClassName" not in pvc["spec"]

    def test_prod_asks_for_the_size_its_snapshot_declares(self, build, tmp_path: Path) -> None:
        pvc = _one(_objects(build("prod"), tmp_path), "PersistentVolumeClaim", "sample-data")

        assert pvc["spec"]["resources"]["requests"]["storage"] == "5Gi"


class TestCronJob:
    def _job(self, build, tmp_path: Path, secrets: bool = False) -> dict[str, Any]:
        return _one(_objects(build(secrets=secrets), tmp_path), "CronJob", "sample-daily")

    def test_runs_on_the_contracts_schedule_in_utc_and_never_overlaps(self, build, tmp_path: Path) -> None:
        spec = self._job(build, tmp_path)["spec"]

        assert spec["schedule"] == "0 6 * * *"
        assert spec["timeZone"] == "Etc/UTC"
        assert spec["concurrencyPolicy"] == "Forbid"

    def test_retries_twice_and_stops_a_run_after_the_deadline(self, build, tmp_path: Path) -> None:
        job = self._job(build, tmp_path)["spec"]["jobTemplate"]["spec"]

        assert job["backoffLimit"] == 2
        assert job["activeDeadlineSeconds"] == 900

    def test_runs_the_command_as_argv_on_the_apps_image_without_restarting(self, build, tmp_path: Path) -> None:
        pod = self._job(build, tmp_path)["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        (container,) = pod["containers"]

        assert pod["restartPolicy"] == "Never"
        assert container["image"] == f"{HOST}/personal/kubelab-sample:sha-1111111"
        assert container["command"] == ["sample", "daily"]

    def test_takes_the_apps_config_and_pull_secret(self, build, tmp_path: Path) -> None:
        pod = self._job(build, tmp_path)["spec"]["jobTemplate"]["spec"]["template"]["spec"]

        assert pod["imagePullSecrets"] == [{"name": pull_secret_name(HOST)}]
        assert pod["containers"][0]["envFrom"] == [{"configMapRef": {"name": "sample-config"}}]

    def test_takes_the_apps_secrets_only_when_it_maps_some(self, build, tmp_path: Path) -> None:
        pod = self._job(build, tmp_path, secrets=True)["spec"]["jobTemplate"]["spec"]["template"]["spec"]

        assert pod["containers"][0]["envFrom"] == [
            {"configMapRef": {"name": "sample-config"}},
            {"secretRef": {"name": "sample-secrets"}},
        ]

    def test_mounts_the_named_volume_and_owns_it_by_the_fs_group(self, build, tmp_path: Path) -> None:
        pod = self._job(build, tmp_path)["spec"]["jobTemplate"]["spec"]["template"]["spec"]

        assert pod["volumes"] == [{"name": "data", "persistentVolumeClaim": {"claimName": "sample-data"}}]
        assert pod["containers"][0]["volumeMounts"] == [{"name": "data", "mountPath": "/data"}]
        assert pod["securityContext"] == {"fsGroup": 10001, "fsGroupChangePolicy": "OnRootMismatch"}


class TestDeploymentMountingAClaim:
    def _deployment(self, build, tmp_path: Path) -> dict[str, Any]:
        return _one(_objects(build(), tmp_path), "Deployment", "sample")

    def test_recreates_rather_than_surges(self, build, tmp_path: Path) -> None:
        """A surge pod cannot open a WAL database the old pod still holds (D5)."""
        assert self._deployment(build, tmp_path)["spec"]["strategy"] == {"type": "Recreate"}

    def test_mounts_the_claim_at_its_path(self, build, tmp_path: Path) -> None:
        pod = self._deployment(build, tmp_path)["spec"]["template"]["spec"]

        assert pod["volumes"] == [{"name": "data", "persistentVolumeClaim": {"claimName": "sample-data"}}]
        assert pod["containers"][0]["volumeMounts"] == [{"name": "data", "mountPath": "/data"}]

    def test_owns_the_volume_by_the_fs_group(self, build, tmp_path: Path) -> None:
        pod = self._deployment(build, tmp_path)["spec"]["template"]["spec"]

        assert pod["securityContext"] == {"fsGroup": 10001, "fsGroupChangePolicy": "OnRootMismatch"}

    def test_sets_no_security_context_when_the_claim_names_no_fs_group(
        self, build, snapshots: Path, tmp_path: Path
    ) -> None:
        (snapshots / "sample.yaml").write_text(_contract(fs_group=None), encoding="utf-8")

        pod = _one(_objects(build(), tmp_path), "Deployment", "sample")["spec"]["template"]["spec"]

        assert "securityContext" not in pod
        assert pod["containers"][0]["volumeMounts"]  # still mounted


class TestConflictingFsGroups:
    def test_two_volumes_naming_different_groups_are_refused(self, build, snapshots: Path) -> None:
        """A pod has one `fsGroup`; picking one of two would leave a volume owned by the wrong group."""
        other = "  logs:\n    type: volume\n    params: {size: 1Gi, mount_path: /logs, fs_group: 20002}\n"
        (snapshots / "sample.yaml").write_text(_contract() + other, encoding="utf-8")

        with pytest.raises(ValueError, match=r"sample.*fs_group.*10001.*20002"):
            build()

    def test_two_volumes_naming_the_same_group_are_accepted(self, build, snapshots: Path) -> None:
        other = "  logs:\n    type: volume\n    params: {size: 1Gi, mount_path: /logs, fs_group: 10001}\n"
        (snapshots / "sample.yaml").write_text(_contract() + other, encoding="utf-8")

        sample = next(a for a in build()["apps"] if a["name"] == "sample")

        assert sample["fs_group"] == 10001


class TestAppWithoutClaims:
    def test_keeps_the_rolling_update_and_no_volume(self, build, tmp_path: Path) -> None:
        deployment = _one(_objects(build(), tmp_path), "Deployment", "api")

        assert deployment["spec"]["strategy"]["type"] == "RollingUpdate"
        pod = deployment["spec"]["template"]["spec"]
        assert "volumes" not in pod
        assert "securityContext" not in pod
        assert "volumeMounts" not in pod["containers"][0]

    def test_gets_neither_a_pvc_nor_a_cronjob(self, build, tmp_path: Path) -> None:
        objects = _objects(build(), tmp_path)

        claimed = [o["metadata"]["name"] for o in objects if o["kind"] in ("PersistentVolumeClaim", "CronJob")]
        assert all(name.startswith("sample-") for name in claimed), claimed


class TestLabels:
    def test_every_object_of_a_claiming_app_carries_its_name_label(self, build, tmp_path: Path) -> None:
        """The ADR-061 classification gate attributes a claim to its product by this label."""
        objects = _objects(build(), tmp_path)

        for kind in ("PersistentVolumeClaim", "CronJob"):
            (obj,) = [o for o in objects if o["kind"] == kind]
            assert obj["metadata"]["labels"]["app.kubernetes.io/name"] == "sample", kind
        cronjob = _one(objects, "CronJob", "sample-daily")
        pod_labels = cronjob["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"]
        assert pod_labels["app.kubernetes.io/name"] == "sample"

    def test_the_service_does_not_select_the_cronjob_pods(self, build, tmp_path: Path) -> None:
        """The job pod has no readiness probe and is Ready while it runs: a Service that matched it
        would send the app's traffic to a pod with nothing listening."""
        objects = _objects(build(), tmp_path)

        selector = _one(objects, "Service", "sample")["spec"]["selector"]
        deployment_pod = _one(objects, "Deployment", "sample")["spec"]["template"]["metadata"]["labels"]
        job_pod = _one(objects, "CronJob", "sample-daily")["spec"]["jobTemplate"]["spec"]["template"]["metadata"][
            "labels"
        ]
        assert selector.items() <= deployment_pod.items()
        assert not selector.items() <= job_pod.items()

    def test_an_app_without_a_job_keeps_the_one_label_selector(self, build, tmp_path: Path) -> None:
        objects = _objects(build(), tmp_path)

        assert _one(objects, "Service", "api")["spec"]["selector"] == {"app.kubernetes.io/name": "api"}


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_the_committed_overlays_render_no_claim(overlay: str) -> None:
    """No product in the repo declares `resources:` yet, so the overlays must hold none of its objects."""
    if shutil.which("kubectl") is None:
        if os.environ.get("CI"):
            pytest.fail("kubectl not on PATH in CI: the overlays went unchecked")
        pytest.skip("kubectl not on PATH: cannot render the overlays (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    objects = [d for d in yaml.safe_load_all(out) if d]
    # The base holds hand-written PVCs and CronJobs; what the toolkit generates carries managed-by: toolkit.
    generated = [o for o in objects if o["metadata"].get("labels", {}).get("app.kubernetes.io/managed-by") == "toolkit"]

    assert not [o for o in generated if o["kind"] in ("PersistentVolumeClaim", "CronJob")]
    strategies = {o["spec"]["strategy"]["type"] for o in generated if o["kind"] == "Deployment"}
    assert strategies == {"RollingUpdate"}
