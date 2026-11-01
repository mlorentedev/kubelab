"""Gitea resolves its webhook targets through public DNS, never the LAN resolver.

Gitea refuses to deliver a webhook to a private or CGNAT address
(`[webhook] ALLOWED_HOST_LIST`, default `external`). The Beelink's host resolver
holds both public servers and the LAN gateway, and systemd-resolved answers from
whichever one is current. The LAN gateway's CoreDNS maps every prod name to the
VPS's tailnet address (see test_coredns_prod_zone_targets.py), so a container that
inherits the host resolver gets 100.64.0.2 for `pr-agent.kubelab.live` part of the
time, and Gitea denies the delivery: `deny pr-agent.kubelab.live(100.64.0.2:443)`.

Pinning the container to public resolvers makes every webhook target resolve to
the public address. MagicDNS is not a fix here: with `override_local_dns: false` it
forwards non-split names to the same host resolvers, so the flip comes back.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"
COMMON = REPO / "infra/config/values/common.yaml"


def _gitea_service() -> dict:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    env.filters["bool"] = bool  # the one Ansible filter the template uses
    rendered = env.from_string((ROLE / "templates/compose.yml.j2").read_text(encoding="utf-8")).render(**defaults)
    return yaml.safe_load(rendered)["services"]["gitea"]


def test_gitea_pins_its_resolvers() -> None:
    assert _gitea_service().get("dns"), "the gitea service inherits the host resolver, which includes the LAN gateway"


def test_no_pinned_resolver_answers_with_lan_or_tailnet_addresses() -> None:
    networking = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]
    private = [ipaddress.ip_network(networking[k]) for k in ("lan_cidr", "tailscale_cidr")]
    for server in _gitea_service()["dns"]:
        address = ipaddress.ip_address(str(server))
        assert not address.is_private, f"{server} is a private resolver"
        assert not any(address in net for net in private), f"{server} is a LAN or tailnet resolver"
