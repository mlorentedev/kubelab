"""#2482: Uptime Kuma's direct port answers only the machines that need it.

Kuma is published on rpi3's tailnet address, and the tailnet has no ACL in force,
so every node could open it and skip the Authelia perimeter in front of
`status.kubelab.live`. A ufw rule cannot close a Docker-published port (DNAT runs
before ufw's chains), so the `rpi3_services` role installs a `KUMA-ALLOW` chain,
jumped to from `DOCKER-USER`, that returns for the allowed sources and drops the
rest.

The sources are derived, never listed: the node of each Argo CD spoke (both K3s
Traefiks route `status.*` to Kuma through `base/external/uptime-kuma.yaml`) and
every `networking.operator_workstations` entry (`make monitoring-apply` and
break-glass reach the port directly). These tests render the role's inputs the way
Ansible does and hold them to that derivation.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
VALUES = REPO / "infra/config/values"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-rpi3.yml"
ROLE = REPO / "infra/ansible/roles/rpi3_services"
CHAIN = "KUMA-ALLOW"


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _config() -> dict[str, Any]:
    """common.yaml with prod's overrides, as the playbook's `config` fact (deploy_env: prod)."""
    common = yaml.safe_load((VALUES / "common.yaml").read_text())
    return _merge(common, yaml.safe_load((VALUES / "prod.yaml").read_text()) or {})


def _role_vars() -> dict[str, str]:
    plays = yaml.safe_load(PLAYBOOK.read_text())
    play = next(p for p in plays if any("rpi3_services" in str(r.get("role")) for r in p.get("roles", [])))
    return next(r for r in play["roles"] if "rpi3_services" in str(r["role"]))["vars"]


def _render(expression: str, **context: Any) -> Any:
    env = Environment(undefined=StrictUndefined)
    return env.from_string(expression).render(config=_config(), **context)


def allowed_sources() -> list[str]:
    """The role's `uptime_kuma_allowed_sources`, rendered from the playbook's expression."""
    rendered = _render(_role_vars()["uptime_kuma_allowed_sources"])
    return yaml.safe_load(rendered)


def expected_sources() -> set[str]:
    config = _config()
    net = config["networking"]
    spokes = {
        net["vps"]["tailscale_ip"] if spoke["node"] == "vps" else net["nodes"][spoke["node"]]["tailscale_ip"]
        for spoke in config["argocd"]["spokes"].values()
    }
    return spokes | {ws["tailscale_ip"] for ws in net["operator_workstations"]}


def test_the_sources_are_each_spoke_node_and_each_operator_workstation() -> None:
    sources = allowed_sources()
    assert sorted(sources) == sorted(expected_sources())
    assert len(sources) == len(set(sources)), f"duplicate sources: {sources}"


def test_the_playbook_lists_no_address() -> None:
    expression = _role_vars()["uptime_kuma_allowed_sources"]
    assert not re.search(r"\d+\.\d+\.\d+\.\d+", expression), "the allowlist must be derived, not listed"


def test_every_workstation_is_a_named_tailnet_address() -> None:
    net = _config()["networking"]
    tailnet = ipaddress.ip_network(net["tailscale_cidr"])
    for ws in net["operator_workstations"]:
        assert ws["name"], ws
        assert ipaddress.ip_address(ws["tailscale_ip"]) in tailnet, ws


def test_kuma_itself_is_not_an_allowed_source() -> None:
    # The node that publishes the port never reaches it through tailscale0.
    assert _config()["networking"]["nodes"]["rpi3"]["tailscale_ip"] not in allowed_sources()


def _rules() -> list[str]:
    template = (ROLE / "templates/kuma-allowlist.rules.j2").read_text()
    text = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True).from_string(template)
    rendered = text.render(ansible_managed="managed", uptime_kuma_allowed_sources=allowed_sources())
    return [line for line in rendered.splitlines() if line and not line.startswith("#")]


def test_the_chain_returns_for_each_source_then_logs_and_drops() -> None:
    rules = _rules()
    assert rules[0] == "*filter" and rules[-1] == "COMMIT"
    # Declaring the chain in a --noflush restore empties it in the same transaction,
    # so a re-apply replaces the list instead of appending to it.
    assert rules[1] == f":{CHAIN} - [0:0]"
    # Kuma's replies carry the same original destination as the request, so they
    # reach the chain too, sourced from the container. Applied without this line
    # on 2026-10-21, it dropped every reply and took status.kubelab.live down.
    assert rules[2] == f"-A {CHAIN} -m conntrack --ctdir REPLY -j RETURN"
    body = rules[3:-1]
    returns = [r for r in body if r.endswith("-j RETURN")]
    assert sorted(returns) == sorted(f"-A {CHAIN} -s {src}/32 -j RETURN" for src in allowed_sources())
    assert body[: len(returns)] == returns, "every RETURN must come before the drop"
    assert "-j LOG" in body[-2] and "--limit" in body[-2], "a dropped source must be visible, rate-limited"
    assert body[-1] == f"-A {CHAIN} -j DROP"


def _unit() -> str:
    template = (ROLE / "templates/kubelab-kuma-allowlist.service.j2").read_text()
    return Environment(undefined=StrictUndefined).from_string(template).render(
        ansible_managed="managed", rpi3_deploy_dir="/opt/monitoring", tailscale_ip="100.64.0.6", uptime_kuma_port=3001
    )


def test_the_unit_follows_docker() -> None:
    unit = _unit()
    # Docker owns DOCKER-USER: start after it, restart and stop with it.
    for line in ("After=docker.service", "PartOf=docker.service", "WantedBy=docker.service"):
        assert line in unit, line
    assert "RemainAfterExit=yes" in unit


def test_the_jump_matches_the_published_address_from_any_interface() -> None:
    unit = _unit()
    jump = "-p tcp -m conntrack --ctorigdst 100.64.0.6 --ctorigdstport 3001 -j KUMA-ALLOW"
    assert f"iptables -w -C DOCKER-USER {jump} || iptables -w -I DOCKER-USER 1 {jump}" in unit
    assert "-i " not in unit, "an interface match would let any other path in"
    assert f"iptables -w -D DOCKER-USER {jump}" in unit, "stopping the unit must remove the jump it added"
