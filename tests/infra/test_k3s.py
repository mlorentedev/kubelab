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


#: IDP-031 LimitRange defaults, stated independently of the manifest under test.
#: These are deliberately literal rather than parsed from
#: `infra/k8s/base/governance/limitrange.yaml`: a test that reads its expectation
#: from the file it validates compares intent against intent and passes for any
#: pair of values, which is how `tls: {}` survived months in prod (docs/lessons.md,
#: 2026-08-09). Changing these values is meant to require touching two places.
EXPECTED_DEFAULT_REQUEST_MEMORY = "128Mi"
EXPECTED_DEFAULT_LIMIT_MEMORY = "256Mi"

#: OBS-009 kube-system LimitRange defaults. Deliberately smaller-request /
#: larger-limit than the kubelab tier above: the request only has to clear
#: lightweight system pods (svclb ~2Mi observed), but the limit has to clear
#: Traefik's real footprint (149-170Mi observed at rest, 2026-08-13) since a
#: LimitRange can't be scoped per-workload — Traefik inherits the same
#: default as everything else in this namespace.
EXPECTED_KUBE_SYSTEM_DEFAULT_REQUEST_MEMORY = "64Mi"
EXPECTED_KUBE_SYSTEM_DEFAULT_LIMIT_MEMORY = "384Mi"


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


class TestNamespaceGovernance:
    """IDP-031: the kubelab namespace bounds every container's memory.

    A `ResourceQuota` rejects any pod that omits a dimension the quota
    constrains, and this namespace ships initContainers that declare no
    resources at all (`apprise/seed-config`, `crowdsec/inject-whitelist`).
    The `LimitRange` is what makes those pods admissible, so it must be live
    and proven *before* a quota is ever added. These tests are the proof.
    """

    def test_limitrange_defaults_memory(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        """The namespace has a LimitRange supplying both memory defaults."""
        result = _kubectl("get limitrange -n kubelab -o json", env)
        assert result.returncode == 0, f"kubectl get limitrange failed: {result.stderr}"

        items = json.loads(result.stdout).get("items", [])
        assert items, "No LimitRange in the kubelab namespace — nothing bounds an unspecified container"

        container_limits = [
            limit
            for lr in items
            for limit in lr.get("spec", {}).get("limits", [])
            if limit.get("type") == "Container"
        ]
        assert container_limits, f"LimitRange(s) present but none of type Container: {[i['metadata']['name'] for i in items]}"

        defaulted_request = {limit.get("defaultRequest", {}).get("memory") for limit in container_limits}
        defaulted_limit = {limit.get("default", {}).get("memory") for limit in container_limits}

        assert EXPECTED_DEFAULT_REQUEST_MEMORY in defaulted_request, (
            f"LimitRange defaultRequest.memory is {defaulted_request}, expected {EXPECTED_DEFAULT_REQUEST_MEMORY}"
        )
        assert EXPECTED_DEFAULT_LIMIT_MEMORY in defaulted_limit, (
            f"LimitRange default.memory is {defaulted_limit}, expected {EXPECTED_DEFAULT_LIMIT_MEMORY}"
        )

    def test_unspecified_container_is_defaulted(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        """A pod declaring no resources is admitted and comes back defaulted.

        Uses a server-side dry run: it traverses the real admission chain — of
        which LimitRanger is a member — and returns the mutated object without
        persisting it. That keeps the whole infra suite read-only, so this is
        safe to run against prod, while still exercising the only thing that
        can actually reject a pod. Asserting against today's two unbounded
        initContainers alone would stop being a check the moment someone gives
        them explicit resources; this keeps the criterion honest for every
        manifest added later.
        """
        manifest = (
            '{"apiVersion":"v1","kind":"Pod",'
            '"metadata":{"name":"idp-031-defaulting-probe","namespace":"kubelab"},'
            '"spec":{"containers":[{"name":"probe","image":"registry.k8s.io/pause:3.9"}]}}'
        )
        result = _kubectl(
            f"create --dry-run=server -o json -f - <<'EOF'\n{manifest}\nEOF",
            env,
            timeout=30,
        )
        assert result.returncode == 0, (
            "A pod with no resources block was REJECTED at admission — the LimitRange "
            f"defaults are missing or invalid: {result.stderr.strip()}"
        )

        resources = json.loads(result.stdout)["spec"]["containers"][0].get("resources", {})
        assert resources.get("requests", {}).get("memory") == EXPECTED_DEFAULT_REQUEST_MEMORY, (
            f"Admitted pod carries requests.memory={resources.get('requests', {}).get('memory')!r}, "
            f"expected the LimitRange to inject {EXPECTED_DEFAULT_REQUEST_MEMORY}"
        )
        assert resources.get("limits", {}).get("memory") == EXPECTED_DEFAULT_LIMIT_MEMORY, (
            f"Admitted pod carries limits.memory={resources.get('limits', {}).get('memory')!r}, "
            f"expected the LimitRange to inject {EXPECTED_DEFAULT_LIMIT_MEMORY}"
        )


class TestKubeSystemGovernance:
    """OBS-009: kube-system bounds every container's memory, same as kubelab.

    Traefik and svclb ship with no declared resources at all, and svclb has
    no other bounding mechanism (verified against k3s's servicelb.go: the
    generated DaemonSet carries no Resources field and no annotation covers
    it). A LimitRange is the only tool that exists for this namespace.

    Applied via the cluster_bootstrap SSOT, not the kubelab-scoped Kustomize
    overlay — that overlay's `namespace: kubelab` override would silently
    rewrite this object into a second kubelab LimitRange if it were ever
    registered there.
    """

    def test_limitrange_defaults_memory(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        """The kube-system namespace has a LimitRange supplying both memory defaults."""
        result = _kubectl("get limitrange -n kube-system -o json", env)
        assert result.returncode == 0, f"kubectl get limitrange failed: {result.stderr}"

        items = json.loads(result.stdout).get("items", [])
        assert items, "No LimitRange in kube-system — Traefik and svclb remain unbounded"

        container_limits = [
            limit
            for lr in items
            for limit in lr.get("spec", {}).get("limits", [])
            if limit.get("type") == "Container"
        ]
        assert container_limits, f"LimitRange(s) present but none of type Container: {[i['metadata']['name'] for i in items]}"

        defaulted_request = {limit.get("defaultRequest", {}).get("memory") for limit in container_limits}
        defaulted_limit = {limit.get("default", {}).get("memory") for limit in container_limits}

        assert EXPECTED_KUBE_SYSTEM_DEFAULT_REQUEST_MEMORY in defaulted_request, (
            f"kube-system LimitRange defaultRequest.memory is {defaulted_request}, "
            f"expected {EXPECTED_KUBE_SYSTEM_DEFAULT_REQUEST_MEMORY}"
        )
        assert EXPECTED_KUBE_SYSTEM_DEFAULT_LIMIT_MEMORY in defaulted_limit, (
            f"kube-system LimitRange default.memory is {defaulted_limit}, "
            f"expected {EXPECTED_KUBE_SYSTEM_DEFAULT_LIMIT_MEMORY}"
        )

    def test_unspecified_container_is_defaulted(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        """A pod declaring no resources in kube-system is admitted and comes back defaulted.

        Same `--dry-run=server` rationale as the kubelab sibling test: traverses
        real admission (LimitRanger included) without persisting, so this stays
        read-only and safe against prod.
        """
        manifest = (
            '{"apiVersion":"v1","kind":"Pod",'
            '"metadata":{"name":"obs-009-defaulting-probe","namespace":"kube-system"},'
            '"spec":{"containers":[{"name":"probe","image":"registry.k8s.io/pause:3.9"}]}}'
        )
        result = _kubectl(
            f"create --dry-run=server -o json -f - <<'EOF'\n{manifest}\nEOF",
            env,
            timeout=30,
        )
        assert result.returncode == 0, (
            "A pod with no resources block was REJECTED at admission in kube-system — the "
            f"LimitRange defaults are missing or invalid: {result.stderr.strip()}"
        )

        resources = json.loads(result.stdout)["spec"]["containers"][0].get("resources", {})
        assert resources.get("requests", {}).get("memory") == EXPECTED_KUBE_SYSTEM_DEFAULT_REQUEST_MEMORY, (
            f"Admitted pod carries requests.memory={resources.get('requests', {}).get('memory')!r}, "
            f"expected the LimitRange to inject {EXPECTED_KUBE_SYSTEM_DEFAULT_REQUEST_MEMORY}"
        )
        assert resources.get("limits", {}).get("memory") == EXPECTED_KUBE_SYSTEM_DEFAULT_LIMIT_MEMORY, (
            f"Admitted pod carries limits.memory={resources.get('limits', {}).get('memory')!r}, "
            f"expected the LimitRange to inject {EXPECTED_KUBE_SYSTEM_DEFAULT_LIMIT_MEMORY}"
        )
