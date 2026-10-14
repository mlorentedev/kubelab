"""#1974: a monitor's `on-demand` tag follows the tier of what it watches.

`muted_notification_tags` is `[staging, on-demand]`, and muting is entirely
tag-driven (`monitoring_diff.wants_notifications`). The always-on RPi3 watches
several on-demand homelab targets, which read DOWN correctly whenever the homelab
is off. Seven of them carried no `on-demand` tag, so every evening the homelab
slept they paged, and a channel that pages for nothing teaches the operator to
ignore it.

Both directions are checked. A missing tag pages for a machine that is off by
design; an extra tag silences a real outage on an always-on host, which is the
worse of the two.

A monitor's target is resolved against the SSOT, never by its name: a node by its
Tailscale address or its `<name>.kubelab.internal` MagicDNS name, a service by its
domain, a backup heartbeat by the node in its key. The tier is the node's or the
service's `location` (ADR-028).
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
MONITORS = json.loads((REPO / "infra/config/uptime-kuma/monitors.json").read_text(encoding="utf-8"))
TAG = "on-demand"
BACKUP_PREFIX = "ops-backup-node-"


def _node_tiers() -> dict[str, str]:
    """Every address or name a monitor may use for a host, mapped to its tier."""
    networking = COMMON["networking"]
    hosts = dict(networking["nodes"])
    hosts.update({key: networking[key] for key in ("vps", "gcp", "aws") if key in networking})
    tiers: dict[str, str] = {}
    for key, node in hosts.items():
        tier = node["location"]
        for name in {key, node.get("hostname")} - {None}:
            tiers[name] = tier
            tiers[f"{name}.kubelab.internal"] = tier
        for field in ("tailscale_ip", "public_ip"):
            if node.get(field):
                tiers[node[field]] = tier
    return tiers


def _service_tiers() -> dict[str, str]:
    """Every service domain that declares a tier."""
    tiers: dict[str, str] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("domain") and node.get("location"):
                tiers[node["domain"]] = node["location"]
            for value in node.values():
                walk(value)

    walk(COMMON["apps"])
    return tiers


NODES = _node_tiers()
SERVICES = _service_tiers()


def _tier(monitor: dict) -> str | None:
    """The tier of what the monitor watches, or None when the SSOT does not say."""
    if monitor["key"].startswith(BACKUP_PREFIX):
        return NODES.get(monitor["key"].removeprefix(BACKUP_PREFIX))
    for target in (monitor.get("dns_resolve_server"), monitor.get("hostname")):
        if target in NODES:
            return NODES[target]
    host = urlsplit(monitor.get("url") or "").hostname
    return NODES.get(host) or SERVICES.get(host)


RESOLVED = [(m["key"], _tier(m), TAG in m.get("tags", [])) for m in MONITORS if _tier(m)]


def test_the_resolver_reaches_both_tiers() -> None:
    """The vacuity check: a renamed SSOT key would otherwise resolve nothing."""
    tiers = [tier for _, tier, _ in RESOLVED]
    assert tiers.count("on-demand") >= 8 and tiers.count("always-on") >= 5, RESOLVED


@pytest.mark.parametrize(("key", "tier", "tagged"), RESOLVED, ids=[key for key, _, _ in RESOLVED])
def test_the_tag_follows_the_tier(key: str, tier: str, tagged: bool) -> None:
    if tier == "on-demand":
        assert tagged, f"{key} watches an on-demand target without the `{TAG}` tag, so it pages whenever the homelab is off"
    else:
        assert not tagged, f"{key} watches an {tier} target but carries `{TAG}`, which silences a real outage"


def test_the_tag_is_muted() -> None:
    """Without this the tag is a label, not a mute."""
    assert TAG in COMMON["apps"]["services"]["observability"]["uptime_kuma"]["muted_notification_tags"]
