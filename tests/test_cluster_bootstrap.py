"""Integration check: _load_cluster_bootstrap reads the real common.yaml SSOT (TOOL-009)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from toolkit.cli.infra import _load_cluster_bootstrap
from toolkit.features.k8s_render import BootstrapEntry

ROOT = Path(__file__).resolve().parent.parent
K8S = ROOT / "infra" / "k8s"


def test_loads_expected_entries() -> None:
    names = {e.name for e in _load_cluster_bootstrap()}
    assert {"agent-sandbox", "coredns-custom"} <= names


def test_agent_sandbox_is_versioned_operator() -> None:
    entry = next(e for e in _load_cluster_bootstrap() if e.name == "agent-sandbox")
    assert entry.version == "v0.5.0rc1"
    assert entry.namespace == "agent-sandbox-system"
    assert entry.render == {}  # static operator — no deploy-time placeholders
    assert entry.optional is False


def test_coredns_is_rendered_and_optional() -> None:
    entry = next(e for e in _load_cluster_bootstrap() if e.name == "coredns-custom")
    assert entry.optional is True  # RPi4 on-demand — skip when off
    assert entry.render == {"RESOLVE_RPI4_TAILSCALE_IP": "rpi4.kubelab.internal"}
    assert entry.version is None  # config, not a versioned operator


def _kustomize_resources() -> Iterator[tuple[Path, Path]]:
    """(kustomization file, resolved path) for every `resources:` entry under infra/k8s."""
    for kustomization in K8S.rglob("kustomization.yaml"):
        doc = yaml.safe_load(kustomization.read_text(encoding="utf-8")) or {}
        for resource in doc.get("resources") or []:
            yield kustomization, (kustomization.parent / resource).resolve()


def test_the_kustomize_scan_reaches_the_base() -> None:
    """Without this, a moved base would make the guard below pass over nothing."""
    assert any(k == K8S / "base" / "kustomization.yaml" for k, _ in _kustomize_resources())


@pytest.mark.parametrize("entry", _load_cluster_bootstrap(), ids=lambda e: e.name)
def test_a_bootstrap_manifest_is_never_a_kustomize_resource(entry: BootstrapEntry) -> None:
    """The bootstrap layer applies these outside the overlay on purpose (OBS-009).

    The overlays set `namespace: kubelab`, so a manifest listed there is rewritten
    into a second `kubelab` object, and the namespace it was written for (here
    kube-system) silently goes ungoverned. Nothing else fails: the adversarial
    review of OBS-009 added the LimitRange to the base and the whole suite passed.
    """
    manifest = (ROOT / entry.manifest).resolve()
    hits = [
        f"{k.relative_to(ROOT)} lists {r.relative_to(ROOT)}"
        for k, r in _kustomize_resources()
        if r == manifest or (r.is_dir() and not (r / "kustomization.yaml").exists() and manifest.is_relative_to(r))
    ]
    assert not hits, f"{entry.name} is applied by cluster_bootstrap and must not be a Kustomize resource: {hits}"
