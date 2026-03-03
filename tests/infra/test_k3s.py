"""Infrastructure: K3s cluster health — node status, pods, PVCs."""

from __future__ import annotations

import json

import pytest

from .fixtures import NodeInfo, ssh_run

pytestmark = pytest.mark.infra

# K3s commands run on the server node
_KUBECTL = "sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml"


def _find_k3s_server(inventory: list[NodeInfo]) -> NodeInfo | None:
    """Find the k3s-server node in the inventory."""
    for node in inventory:
        if "k3s-server" in node.name:
            return node
    return None


class TestK3sCluster:
    """K3s cluster must be healthy with all nodes ready."""

    def test_all_nodes_ready(
        self,
        inventory: list[NodeInfo],
        env: str,
    ) -> None:
        if env == "dev":
            pytest.skip("No K3s cluster in dev")

        server = _find_k3s_server(inventory)
        if not server:
            pytest.skip("k3s-server not in inventory")

        result = ssh_run(
            server.host,
            f"{_KUBECTL} get nodes -o json",
            timeout=15,
        )
        assert result.returncode == 0, f"kubectl get nodes failed: {result.stderr}"

        data = json.loads(result.stdout)
        nodes = data.get("items", [])
        assert nodes, "No K3s nodes found"

        not_ready: list[str] = []
        for node in nodes:
            name = node["metadata"]["name"]
            conditions = node.get("status", {}).get("conditions", [])
            ready = any(
                c["type"] == "Ready" and c["status"] == "True"
                for c in conditions
            )
            if not ready:
                not_ready.append(name)

        assert not not_ready, f"K3s nodes not Ready: {not_ready}"

    def test_no_memory_pressure(
        self,
        inventory: list[NodeInfo],
        env: str,
    ) -> None:
        if env == "dev":
            pytest.skip("No K3s cluster in dev")

        server = _find_k3s_server(inventory)
        if not server:
            pytest.skip("k3s-server not in inventory")

        result = ssh_run(
            server.host,
            f"{_KUBECTL} get nodes -o json",
            timeout=15,
        )
        assert result.returncode == 0, f"kubectl get nodes failed: {result.stderr}"

        data = json.loads(result.stdout)
        pressure: list[str] = []
        for node in data.get("items", []):
            name = node["metadata"]["name"]
            conditions = node.get("status", {}).get("conditions", [])
            for c in conditions:
                if c["type"] == "MemoryPressure" and c["status"] == "True":
                    pressure.append(name)

        assert not pressure, f"K3s nodes with MemoryPressure: {pressure}"

    def test_pods_running_in_namespace(
        self,
        inventory: list[NodeInfo],
        env: str,
    ) -> None:
        if env == "dev":
            pytest.skip("No K3s cluster in dev")

        server = _find_k3s_server(inventory)
        if not server:
            pytest.skip("k3s-server not in inventory")

        result = ssh_run(
            server.host,
            f"{_KUBECTL} get pods -n kubelab -o json",
            timeout=15,
        )
        assert result.returncode == 0, f"kubectl get pods failed: {result.stderr}"

        data = json.loads(result.stdout)
        pods = data.get("items", [])
        assert pods, "No pods found in kubelab namespace"

        not_running: list[str] = []
        for pod in pods:
            name = pod["metadata"]["name"]
            phase = pod.get("status", {}).get("phase", "Unknown")
            if phase not in ("Running", "Succeeded"):
                not_running.append(f"{name} ({phase})")

        assert not not_running, (
            "Pods not Running in kubelab namespace:\n" + "\n".join(not_running)
        )

    def test_pvcs_bound(
        self,
        inventory: list[NodeInfo],
        env: str,
    ) -> None:
        if env == "dev":
            pytest.skip("No K3s cluster in dev")

        server = _find_k3s_server(inventory)
        if not server:
            pytest.skip("k3s-server not in inventory")

        result = ssh_run(
            server.host,
            f"{_KUBECTL} get pvc -n kubelab -o json",
            timeout=15,
        )
        assert result.returncode == 0, f"kubectl get pvc failed: {result.stderr}"

        data = json.loads(result.stdout)
        pvcs = data.get("items", [])

        if not pvcs:
            return  # No PVCs is valid

        not_bound: list[str] = []
        for pvc in pvcs:
            name = pvc["metadata"]["name"]
            phase = pvc.get("status", {}).get("phase", "Unknown")
            if phase != "Bound":
                not_bound.append(f"{name} ({phase})")

        assert not not_bound, (
            "PVCs not Bound in kubelab namespace:\n" + "\n".join(not_bound)
        )
