"""Pinned resolvers are declared once, in `networking.*` (#2901).

Each role had copied the `docker_dns_servers` pattern (MON-001, #911) with its own
literal default, so one pair of addresses lived in six places. A literal in role
defaults is what brings that back, whatever the variable is called.
"""

from __future__ import annotations

import ipaddress
import re
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


def test_no_role_template_names_a_resolver_address() -> None:
    """A template is rendered as it stands, so a literal there skips the SSOT as one in defaults does."""
    literals = {
        f"{p.relative_to(ROLES)}: {a}"
        for p in ROLES.glob("*/templates/*")
        for a in {*PUBLIC, *TAILNET_FIRST}
        if a in _code(p)
    }
    # A different pair, 1.1.1.1 and 1.0.0.1, so moving it changes what clients resolve
    # through and restarts the coordination server: an operator's decision (#2945).
    assert literals == {"headscale/templates/config.yaml.j2: 1.1.1.1"}


def test_the_corefile_forwards_to_the_declared_resolvers() -> None:
    default = yaml.safe_load((ROLES / "coredns/defaults/main.yml").read_text(encoding="utf-8"))["coredns_forwarders"]
    assert "common.networking.public_resolvers | join(' ')" in default
    assert " ".join(PUBLIC) == "1.1.1.1 8.8.8.8", "the Corefile's rendered bytes moved"
    corefile = (ROLES / "coredns/templates/Corefile.j2").read_text(encoding="utf-8")
    assert corefile.count("forward . {{ coredns_forwarders }}") == 2


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


def test_every_resolver_variable_reads_the_ssot() -> None:
    """Catches an address the SSOT does not declare, which the literal scan cannot."""
    variables = {
        f"{path.relative_to(ROLES)}: {name}": value
        for path in ROLES.glob("*/defaults/*.yml")
        for name, value in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items()
        if name.endswith(("dns_servers", "acme_dns_resolvers"))
    }
    tailnet_first = {
        "agent_stack/defaults/main.yml: agent_stack_docker_dns_servers",
        "rpi3_services/defaults/main.yml: docker_dns_servers",
    }
    assert len(variables) == 7, variables
    assert tailnet_first <= variables.keys(), variables
    wrong = {
        name: value
        for name, value in variables.items()
        if (
            "config.networking.tailnet_first_resolvers"
            if name in tailnet_first
            else "config.networking.public_resolvers"
        )
        not in str(value)
    }
    assert not wrong


def test_no_play_overrides_a_resolver_variable() -> None:
    """A play's `vars:` outranks the role default, so a literal there skips the SSOT."""
    overrides = [
        path.name
        for path in (REPO / "infra/ansible/playbooks").glob("*.yml")
        if re.search(r"^\s+\w*(dns_servers|acme_dns_resolvers):", path.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert not overrides
