"""Every workload in `kubelab` is behind an ingress allowlist (NET-002, #378).

A pod no NetworkPolicy selects accepts a connection from any pod in the
cluster. The policies in `infra/k8s/base/governance/networkpolicies.yaml` (plus
Grafana's and PR-Agent's) select every workload, so a workload added without
one fails here rather than shipping open.

The allowlist is also checked against the callers the repository names: an
in-cluster `host:port` in a workload's ConfigMaps or pod spec, in a Traefik
Middleware, or in an n8n workflow, and every IngressRoute backend, must be
allowed by the policy of the pod it reaches. A new caller without a rule is a connection refused in staging, and
this finds it before the deploy does.

Static: it renders both overlays and reads no cluster. Whether kube-router
enforces what it reads is the staging check in the PR.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
OVERLAYS = ["staging", "prod"]
WORKFLOWS = REPO / "infra/n8n/workflows"
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "CronJob", "Job"}
NAME = "app.kubernetes.io/name"
# Traefik is K3s's bundled chart, not in the overlays: the one source that is
# not a pod of the render.
TRAEFIK = {
    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
    "podSelector": {"matchLabels": {NAME: "traefik"}},
}
IMAGE = re.compile(r'"image": "[^"]*"')
ADDRESS = re.compile(r"(?<![\w.-])([a-z][a-z0-9-]*)(?:\.kubelab(?:\.svc(?:\.cluster\.local)?)?)?:(\d{2,5})\b")

_RENDERS: dict[str, list[dict[str, Any]]] = {}


def _render(overlay: str) -> list[dict[str, Any]]:
    if overlay not in _RENDERS:
        if shutil.which("kubectl") is None:
            pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
        out = subprocess.run(
            ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
            capture_output=True,
            text=True,
            check=True,
        )
        _RENDERS[overlay] = [d for d in yaml.safe_load_all(out.stdout) if d]
    return _RENDERS[overlay]


def _pod_spec(workload: dict[str, Any]) -> dict[str, Any]:
    spec = workload["spec"]
    if workload["kind"] == "CronJob":
        spec = spec["jobTemplate"]["spec"]
    return spec["template"]


def _workloads(overlay: str) -> dict[str, dict[str, Any]]:
    return {d["metadata"]["name"]: d for d in _render(overlay) if d["kind"] in WORKLOAD_KINDS}


def _labels(workload: dict[str, Any]) -> dict[str, str]:
    return _pod_spec(workload)["metadata"].get("labels", {})


def _selects(selector: dict[str, Any], labels: dict[str, str]) -> bool:
    """Kubernetes semantics: an empty selector selects every pod."""
    assert "matchExpressions" not in selector, f"matchExpressions is not modelled here: {selector}"
    return all(labels.get(k) == v for k, v in selector.get("matchLabels", {}).items())


def _policies(overlay: str) -> list[dict[str, Any]]:
    return [d for d in _render(overlay) if d["kind"] == "NetworkPolicy" and "Ingress" in d["spec"]["policyTypes"]]


def _policy_for(overlay: str, workload: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in _policies(overlay) if _selects(p["spec"]["podSelector"], _labels(workload))]


def _container_port(workload: dict[str, Any], target: int | str) -> int:
    if isinstance(target, int):
        return target
    for c in _pod_spec(workload)["spec"]["containers"]:
        for p in c.get("ports", []):
            if p.get("name") == target:
                return int(p["containerPort"])
    raise AssertionError(f"{workload['metadata']['name']} declares no port named {target}")


def _allowed(overlay: str, source: str, target: dict[str, Any], port: int) -> bool:
    """Does a policy selecting `target` let `source` (a workload name, or
    `traefik`) connect on `port`?"""
    for policy in _policy_for(overlay, target):
        for rule in policy["spec"].get("ingress", []):
            if port not in {p["port"] for p in rule.get("ports", [])}:
                continue
            for peer in rule["from"]:
                if source == "traefik" and peer == TRAEFIK:
                    return True
                if set(peer) == {"podSelector"} and peer["podSelector"]["matchLabels"].get(NAME) == source:
                    return True
    return False


def _workflows() -> list[Path]:
    return sorted(WORKFLOWS.rglob("*.json"))


def _callers(overlay: str) -> set[tuple[str, str, int]]:
    """(caller, Service, Service port) for every in-cluster address the
    repository names, with the caller that uses it."""
    docs = _render(overlay)
    # A Service without a selector is an EndpointSlice outside the cluster,
    # which no policy covers, so only selected Services are targets.
    selected = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Service" and d["spec"].get("selector")}
    # A `host:port` counts only on a port its Service declares: an image tag in
    # a ConfigMap (`postgres:16`) is not a caller.
    ports = {name: {p["port"] for p in svc["spec"]["ports"]} for name, svc in selected.items()}
    configmaps = {d["metadata"]["name"]: json.dumps(d.get("data", {})) for d in docs if d["kind"] == "ConfigMap"}
    texts: list[tuple[str, str]] = []
    for name, workload in _workloads(overlay).items():
        # An image reference (`postgres:16`) reads as host:port.
        pod = IMAGE.sub("", json.dumps(_pod_spec(workload)))
        texts.append((name, pod))
        texts += [(name, text) for cm, text in configmaps.items() if f'"{cm}"' in pod]
    texts += [("traefik", json.dumps(d["spec"])) for d in docs if d["kind"] == "Middleware"]
    texts += [("n8n", f.read_text(encoding="utf-8")) for f in _workflows()]
    found = set()
    for caller, text in texts:
        for host, port in ADDRESS.findall(text):
            if int(port) in ports.get(host, set()) and host != caller:
                found.add((caller, host, int(port)))
    # Every IngressRoute backend, and every Service a Middleware sends to, is a
    # Traefik caller.
    for backend in _route_backends(overlay) + _middleware_backends(overlay):
        svc = selected.get(backend["name"])
        if svc is None:
            continue
        port = next(p["port"] for p in svc["spec"]["ports"] if backend["port"] in (p["port"], p.get("name")))
        found.add(("traefik", backend["name"], port))
    return found


def _route_backends(overlay: str) -> list[dict[str, Any]]:
    routes = (d for d in _render(overlay) if d["kind"] == "IngressRoute")
    return [b for route in routes for r in route["spec"]["routes"] for b in r.get("services", [])]


def _middleware_backends(overlay: str) -> list[dict[str, Any]]:
    """The error-pages Middleware names its Service as `{name, port}`, which
    the `host:port` scan cannot read."""
    middlewares = (d for d in _render(overlay) if d["kind"] == "Middleware")
    return [m["spec"]["errors"]["service"] for m in middlewares if "errors" in m["spec"]]


def _target(overlay: str, service: str, port: int) -> tuple[dict[str, Any], int]:
    svc = next(d for d in _render(overlay) if d["kind"] == "Service" and d["metadata"]["name"] == service)
    selector = {"matchLabels": svc["spec"]["selector"]}
    workload = next(w for w in _workloads(overlay).values() if _selects(selector, _labels(w)))
    target = next(p.get("targetPort", p["port"]) for p in svc["spec"]["ports"] if p["port"] == port)
    return workload, _container_port(workload, target)


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_render_measured_what_it_judges(overlay: str) -> None:
    """A render that found nothing would pass every check below."""
    assert len(_workloads(overlay)) >= 15
    assert len(_policies(overlay)) >= 15
    assert len(_callers(overlay)) >= 14
    # Each source is measured on its own, so losing one cannot hide behind the others.
    assert len(_workflows()) >= 5, "the n8n workflows are no longer where this test reads them"
    assert any(caller == "n8n" for caller, _, _ in _callers(overlay))
    assert _middleware_backends(overlay), (
        "the error-pages Middleware no longer names a Service where this test reads it"
    )


def test_an_empty_selector_selects_every_pod() -> None:
    """A namespace default-deny (`podSelector: {}`) must count as covering every
    workload, not read as a policy that selects nothing."""
    assert _selects({}, {NAME: "anything"})
    assert not _selects({"matchLabels": {NAME: "web"}}, {NAME: "api"})


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_workload_is_selected_by_an_ingress_policy(overlay: str) -> None:
    open_pods = sorted(n for n, w in _workloads(overlay).items() if not _policy_for(overlay, w))
    assert not open_pods, f"workloads any pod can reach (add a policy to networkpolicies.yaml): {open_pods}"


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_policy_selects_a_workload(overlay: str) -> None:
    labels = [_labels(w) for w in _workloads(overlay).values()]
    dead = [
        p["metadata"]["name"]
        for p in _policies(overlay)
        if not any(_selects(p["spec"]["podSelector"], lb) for lb in labels)
    ]
    assert not dead, f"policies that select no pod (a renamed label?): {dead}"


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_rule_names_its_sources_and_ports(overlay: str) -> None:
    """A rule without `from` or `ports` allows everyone on that axis, which
    undoes the deny without looking like it."""
    names = {_labels(w).get(NAME) for w in _workloads(overlay).values()}
    wrong = []
    for policy in _policies(overlay):
        for rule in policy["spec"].get("ingress", []):
            if not rule.get("from") or not rule.get("ports"):
                wrong.append(f"{policy['metadata']['name']}: a rule with no from or no ports")
                continue
            for peer in rule["from"]:
                pod = peer.get("podSelector", {}).get("matchLabels", {}).get(NAME)
                if peer != TRAEFIK and (set(peer) != {"podSelector"} or pod not in names):
                    wrong.append(f"{policy['metadata']['name']}: source {peer} is neither Traefik nor a pod here")
    assert not wrong, "\n".join(wrong)


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_named_caller_is_allowed(overlay: str) -> None:
    refused = []
    for caller, service, port in sorted(_callers(overlay)):
        workload, container_port = _target(overlay, service, port)
        if not _allowed(overlay, caller, workload, container_port):
            refused.append(f"{caller} -> {service}:{port} (pod port {container_port})")
    assert not refused, f"callers the repository names that the policies refuse: {refused}"
