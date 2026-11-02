"""Pinned resolvers are declared once, in `networking.*` (#2901).

Each role had copied the `docker_dns_servers` pattern (MON-001, #911) with its own
literal default, so one pair of addresses lived in six places. A literal in role
defaults is what brings that back, whatever the variable is called.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
ROLES = REPO / "infra" / "ansible" / "roles"
NETWORKING = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))["networking"]
PUBLIC = NETWORKING["public_resolvers"]
TAILNET_FIRST = NETWORKING["tailnet_first_resolvers"]
TAILNET = ipaddress.ip_network(NETWORKING["tailscale_cidr"])


def _code(path: Path) -> str:
    """The file without comments, which may name an address to explain it."""
    return "\n".join(line.split("#", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())


def test_no_role_default_names_a_resolver_address() -> None:
    addresses = {*PUBLIC, *TAILNET_FIRST}
    literals = {
        f"{p.relative_to(ROLES)}: {a}" for p in ROLES.glob("*/defaults/*.yml") for a in addresses if a in _code(p)
    }
    assert not literals


def test_every_public_resolver_is_public() -> None:
    assert PUBLIC
    assert all(ipaddress.ip_address(address).is_global for address in PUBLIC), PUBLIC


def test_the_tailnet_first_list_leads_with_magicdns_and_falls_back_to_a_declared_public_resolver() -> None:
    """Order is the point of this list: a public resolver in front answers NXDOMAIN
    for a split-DNS zone, and that answer is final."""
    assert len(TAILNET_FIRST) == 2
    head, fallback = TAILNET_FIRST
    assert ipaddress.ip_address(head) in TAILNET
    assert fallback in PUBLIC
