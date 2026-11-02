"""The api readiness probe points at /ready, not at the liveness path (kubelab#2386).

#1736 made `/health` a constant-200 liveness signal and gave `/ready` the honest
check, but the generator had one `health_path` for both probes, so nothing in the
platform probed `/ready`. Kubernetes could not take a pod out of rotation for the
one condition `/ready` gates on.

Two halves: the generator resolves a per-app `readiness_path` that defaults to the
liveness path (every other app keeps rendering exactly what it did), and the
COMMITTED generated Deployments for api carry `/ready` in both environments. The
second half reads the files Argo CD actually applies, so it needs no SOPS.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.features.generator_k8s import K8sGenerator

REPO = Path(__file__).resolve().parent.parent


def _find(env_vars: dict[str, str]) -> tuple[str | None, str | None]:
    gen = K8sGenerator()
    return gen._health_paths(env_vars, "api")


class TestReadinessPathResolution:
    def test_defaults_to_the_liveness_path(self) -> None:
        live, ready = _find({"APPS_PLATFORM_API_HEALTH_PATH": "/health"})

        assert (live, ready) == ("/health", "/health")

    def test_a_declared_readiness_path_is_used_for_readiness_only(self) -> None:
        live, ready = _find({"APPS_PLATFORM_API_HEALTH_PATH": "/health", "APPS_PLATFORM_API_READINESS_PATH": "/ready"})

        assert (live, ready) == ("/health", "/ready")

    def test_no_health_path_means_no_probes(self) -> None:
        assert _find({}) == (None, None)

    def test_the_path_is_probe_metadata_and_stays_out_of_the_configmap(self) -> None:
        """Like HEALTH_PATH, it would otherwise land in the pod env and change the ConfigMap hash."""
        env = {"APPS_PLATFORM_API_HEALTH_PATH": "/health", "APPS_PLATFORM_API_READINESS_PATH": "/ready"}

        assert "READINESS_PATH" not in K8sGenerator()._extract_app_env_vars(env, "api")


def _api_probes(env: str) -> dict[str, str]:
    path = REPO / "infra" / "k8s" / "overlays" / env / "generated" / "deployments.yaml"
    for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if doc and doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "api":
            c = doc["spec"]["template"]["spec"]["containers"][0]
            return {
                "liveness": c["livenessProbe"]["httpGet"]["path"],
                "readiness": c["readinessProbe"]["httpGet"]["path"],
            }
    raise AssertionError(f"no api Deployment in {path}")


@pytest.mark.parametrize("env", ["staging", "prod"])
class TestCommittedApiProbes:
    def test_readiness_probes_ready_not_the_liveness_path(self, env: str) -> None:
        probes = _api_probes(env)

        assert probes["readiness"] == "/ready", probes
        assert probes["readiness"] != probes["liveness"], "readiness must not reuse the liveness path"

    def test_liveness_stays_on_health(self, env: str) -> None:
        """A dependency problem must never restart the pod: liveness is /health."""
        assert _api_probes(env)["liveness"] == "/health"
