"""Infrastructure: K3s cluster health — node status, pods, PVCs.

Uses local kubeconfig (~/.kube/kubelab-{env}-config) instead of SSH+sudo
to the K3s server. Requires Tailscale VPN for connectivity.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

pytestmark = pytest.mark.infra

_KUBECONFIG_PATTERN = "~/.kube/kubelab-{env}-config"


def _get_kubeconfig(env: str) -> str:
    env_specific = os.path.expanduser(_KUBECONFIG_PATTERN.format(env=env))
    if os.path.exists(env_specific):
        return env_specific
    if kubeconfig := os.environ.get("KUBECONFIG"):
        return kubeconfig
    return env_specific


def _kubectl(args: str, env: str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    kubeconfig = _get_kubeconfig(env)
    return subprocess.run(
        f"kubectl --kubeconfig {kubeconfig} {args}",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def require_kubeconfig(env: str) -> None:
    kubeconfig = _get_kubeconfig(env)
    if not os.path.exists(kubeconfig):
        pytest.skip(f"Kubeconfig not found: {kubeconfig}")
    result = _kubectl("cluster-info", env, timeout=10)
    if result.returncode != 0:
        pytest.skip(f"K3s cluster unreachable: {result.stderr.strip()}")


class TestK3sCluster:
    """K3s cluster must be healthy with all nodes ready."""

    def test_all_nodes_ready(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        result = _kubectl("get nodes -o json", env)
        assert result.returncode == 0, f"kubectl get nodes failed: {result.stderr}"

        data = json.loads(result.stdout)
        nodes = data.get("items", [])
        assert nodes, "No K3s nodes found"

        not_ready = [
            node["metadata"]["name"]
            for node in nodes
            if not any(
                c["type"] == "Ready" and c["status"] == "True"
                for c in node.get("status", {}).get("conditions", [])
            )
        ]
        assert not not_ready, f"K3s nodes not Ready: {not_ready}"

    def test_no_memory_pressure(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        result = _kubectl("get nodes -o json", env)
        assert result.returncode == 0, f"kubectl get nodes failed: {result.stderr}"

        data = json.loads(result.stdout)
        pressure = [
            node["metadata"]["name"]
            for node in data.get("items", [])
            if any(
                c["type"] == "MemoryPressure" and c["status"] == "True"
                for c in node.get("status", {}).get("conditions", [])
            )
        ]
        assert not pressure, f"K3s nodes with MemoryPressure: {pressure}"

    def test_pods_running_in_namespace(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        result = _kubectl("get pods -n kubelab -o json", env)
        assert result.returncode == 0, f"kubectl get pods failed: {result.stderr}"

        data = json.loads(result.stdout)
        pods = data.get("items", [])
        assert pods, "No pods found in kubelab namespace"

        not_running = [
            f"{pod['metadata']['name']} ({pod.get('status', {}).get('phase', 'Unknown')})"
            for pod in pods
            if pod.get("status", {}).get("phase", "Unknown") not in ("Running", "Succeeded")
        ]
        assert not not_running, "Pods not Running:\n" + "\n".join(not_running)

    def test_pvcs_bound(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        result = _kubectl("get pvc -n kubelab -o json", env)
        assert result.returncode == 0, f"kubectl get pvc failed: {result.stderr}"

        data = json.loads(result.stdout)
        pvcs = data.get("items", [])
        if not pvcs:
            return

        not_bound = [
            f"{pvc['metadata']['name']} ({pvc.get('status', {}).get('phase', 'Unknown')})"
            for pvc in pvcs
            if pvc.get("status", {}).get("phase") != "Bound"
        ]
        assert not not_bound, "PVCs not Bound:\n" + "\n".join(not_bound)
