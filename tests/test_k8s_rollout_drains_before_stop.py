"""A pod Traefik routes to keeps serving until Traefik has dropped it (DELIVERY-012).

SIGTERM and endpoint removal start together, so without a delay the process can
stop while Traefik still routes to it. Measured on staging at 50 requests/s during
a `web` rollout (#2977): 0.34% of requests lost, maximum 5,001 ms, without a
`preStop`. With a 5-second one: 0 of 15,001 lost, maximum 21 ms.

The rule covers every rolling workload behind an IngressRoute, not one app: the
race belongs to the rollout, whatever runs in the pod. A `Recreate` Deployment is
exempt, because it has no second pod to drain to and is down during its rollout
anyway. Read from the rendered overlays, which are what Argo CD applies.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
# Traefik's Kubernetes provider throttles config reloads for 2 seconds, then needs
# to load the new config.
MIN_DRAIN_SECONDS = 5
# Kubernetes' default terminationGracePeriodSeconds, used when a pod spec declares none.
DEFAULT_GRACE_SECONDS = 30


def _render(overlay: str) -> list[dict[str, Any]]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert out.returncode == 0, out.stderr
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def _routed_rolling_workloads(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    routed = {
        service["name"]
        for d in docs
        if d["kind"] == "IngressRoute"
        for route in d["spec"].get("routes", [])
        for service in route.get("services", [])
    }
    selectors = [
        d["spec"]["selector"]
        for d in docs
        if d["kind"] == "Service" and d["metadata"]["name"] in routed and d["spec"].get("selector")
    ]
    workloads = []
    for d in docs:
        if d["kind"] != "Deployment" or d["spec"].get("strategy", {}).get("type") == "Recreate":
            continue
        labels = d["spec"]["template"]["metadata"].get("labels", {})
        if any(all(labels.get(k) == v for k, v in sel.items()) for sel in selectors):
            workloads.append(d)
    return workloads


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_every_routed_rolling_workload_drains_before_it_stops(overlay: str) -> None:
    workloads = _routed_rolling_workloads(_render(overlay))
    assert {w["metadata"]["name"] for w in workloads} >= {"api", "web"}, "the selection found too little"
    for workload in workloads:
        name = workload["metadata"]["name"]
        pod = workload["spec"]["template"]["spec"]
        grace = pod.get("terminationGracePeriodSeconds", DEFAULT_GRACE_SECONDS)
        sleep = pod["containers"][0].get("lifecycle", {}).get("preStop", {}).get("sleep", {})
        assert MIN_DRAIN_SECONDS <= sleep.get("seconds", 0) < grace, f"{name} stops without draining within {grace}s"
