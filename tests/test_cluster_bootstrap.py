"""Integration check: _load_cluster_bootstrap reads the real common.yaml SSOT (TOOL-009)."""

from __future__ import annotations

from toolkit.cli.infra import _load_cluster_bootstrap


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
