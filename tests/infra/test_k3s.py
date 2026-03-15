"""Infrastructure: K3s cluster health — node status, pods, PVCs.

Uses local kubeconfig (~/.kube/kubelab-config) instead of SSH+sudo
to the K3s server. Requires Tailscale VPN for connectivity.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

pytestmark = pytest.mark.infra

_KUBECONFIG = os.path.expanduser("~/.kube/kubelab-config")
_KUBECTL = f"kubectl --kubeconfig {_KUBECONFIG}"


def _kubectl(args: str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        f"{_KUBECTL} {args}",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def require_kubeconfig() -> None:
    if not os.path.exists(_KUBECONFIG):
        pytest.skip(f"Kubeconfig not found: {_KUBECONFIG}")
    result = _kubectl("cluster-info", timeout=10)
    if result.returncode != 0:
        pytest.skip(f"K3s cluster unreachable: {result.stderr.strip()}")


class TestK3sCluster:
    """K3s cluster must be healthy with all nodes ready."""

    def test_all_nodes_ready(self, require_vpn: None, require_kubeconfig: None) -> None:
        result = _kubectl("get nodes -o json")
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

    def test_no_memory_pressure(self, require_vpn: None, require_kubeconfig: None) -> None:
        result = _kubectl("get nodes -o json")
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

    def test_pods_running_in_namespace(self, require_vpn: None, require_kubeconfig: None) -> None:
        result = _kubectl("get pods -n kubelab -o json")
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

    def test_pvcs_bound(self, require_vpn: None, require_kubeconfig: None) -> None:
        result = _kubectl("get pvc -n kubelab -o json")
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
