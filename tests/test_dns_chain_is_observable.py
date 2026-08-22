"""The staging DNS chain must be able to break loudly.

On 2026-08-22 rpi4 rebooted and staging DNS died for roughly ninety minutes.
Nothing alerted. Three separate green signals covered the same hole:

    docker ps                    -> `running`   (the process is alive)
    pihole healthcheck           -> `healthy`   (`dig @127.0.0.1 localhost`)
    monitor infra-vpn-rpi4-...   -> up          (ICMP to 100.64.0.10)

Not one of them touches the chain that matters: client -> Pi-hole -> CoreDNS ->
answer. The host was up, the processes were alive, and nothing resolved.

WHAT ACTUALLY BROKE. CoreDNS published its health port at
`{{ node_ips.rpi4 }}:8080`, a TAILSCALE address. On boot Docker restores
containers under `restart: unless-stopped`, and it got there before tailscaled
had assigned 100.64.0.10. The bind failed and took the container's whole port
publication with it -- including `5353:53`, which is how Pi-hole reaches CoreDNS.
Measured afterwards:

    coredns => (no ports at all)
    pihole  => WARNING: Connection error (172.17.0.1#5353): TCP connection failed

The container was `running` and mute. `docker inspect` still showed the bindings
configured, which is why nothing downstream noticed they were never applied.

This is #959's lesson one level up. That one said a published port is governed
by its bind address; this one says a bind address can also be a BOOT-ORDER
DEPENDENCY, and binding to an interface another service must first bring up
makes container start depend on that service winning a race nothing referees.

Three properties, each closing one of the three false greens.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_TPL = REPO_ROOT / "infra/ansible/roles/coredns/templates/docker-compose.yml.j2"
DEPLOY_DNS = REPO_ROOT / "infra/ansible/playbooks/deploy-dns.yml"
COMMON = REPO_ROOT / "infra/config/values/common.yaml"
SEED = REPO_ROOT / "infra/config/uptime-kuma/monitors.json"


def _compose_text() -> str:
    """Read as TEXT, deliberately.

    The file is a Jinja2 template: `restart: {{ restart_policy }}` is an
    unquoted `{{`, which YAML reads as the start of a nested flow mapping and
    rejects. Parsing it would mean rendering it, and rendering it would mean
    reproducing the playbook's variable wiring here -- a second declaration free
    to drift from the first.
    """
    return COMPOSE_TPL.read_text()


def _seed() -> list[dict]:
    data = json.loads(SEED.read_text())
    return data if isinstance(data, list) else data.get("monitors", data)


# --- 1. the boot-order race -------------------------------------------------


def test_no_published_port_binds_to_a_tailscale_address():
    """A bind address that another service must create is a race, not a control.

    `node_ips.*` are Tailscale addresses (see deploy-dns.yml), and tailscaled
    comes up independently of Docker. Binding a published port to one makes the
    container's ENTIRE port publication depend on winning that race on every
    boot -- and losing it is silent.

    rpi4's LAN address is the right anchor: it is on a physical interface the
    network stack configures before Docker starts, and it is still not a bare
    world-facing publish, so #959's protection is kept rather than traded away.
    """
    text = _compose_text()
    offenders = [
        line.strip()
        for line in text.splitlines()
        if re.search(r'-\s*"\{\{\s*node_ips\.\w+\s*\}\}:', line)
    ]
    assert not offenders, (
        "a published port is bound to a Tailscale address:\n  "
        + "\n  ".join(offenders)
        + "\nOn boot Docker restores containers before tailscaled has assigned the "
        "address; the bind fails and takes every other port on that container with "
        "it. Use the node's LAN address, which exists before Docker starts."
    )


def test_the_lan_address_the_compose_relies_on_exists_in_the_ssot():
    """Guard against fixing the race by inventing an address.

    Hardcoding an IP here would satisfy the test above and violate the repo's
    rule that every address lives in `networking.*`.
    """
    common = yaml.safe_load(COMMON.read_text())
    lan_ip = common["networking"]["nodes"]["rpi4"]["lan_ip"]
    assert lan_ip, "networking.nodes.rpi4.lan_ip is the SSOT this compose must read"
    assert not re.search(rf'\b{re.escape(lan_ip)}\b', _compose_text()), (
        f"the LAN address {lan_ip} is hardcoded in the compose template. It must "
        "arrive as a variable from deploy-dns.yml, which reads common.yaml."
    )


# --- 2. the healthcheck that answers itself ---------------------------------


def test_the_pihole_healthcheck_exercises_the_coredns_chain():
    """`dig @127.0.0.1 localhost` proves Pi-hole is alive, and nothing else.

    Pi-hole answers `localhost` from its own tables without ever consulting its
    upstream, so the probe passed for ninety minutes while every real query
    failed. A healthcheck must resolve a name that ONLY CoreDNS can answer --
    then `healthy` means the chain works, which is the thing being claimed.

    Deliberately a property, not a literal: any staging name will do, and
    pinning one here would break the next time the Corefile's hosts block moves.
    """
    text = _compose_text()
    match = re.search(r'test:\s*\[([^\]]*)\]', text)
    assert match, "the pihole healthcheck disappeared; this guard must be updated with it"
    probe = match.group(1)

    assert "localhost" not in probe, (
        f"the healthcheck resolves `localhost`: {probe}\n"
        "Pi-hole answers that itself, so the probe cannot fail when its upstream "
        "CoreDNS is unreachable -- which is exactly the outage it must catch."
    )
    assert "staging" in probe or "staging_domain" in probe, (
        f"the healthcheck does not resolve a staging name: {probe}\n"
        "Only a name served by CoreDNS proves the Pi-hole -> CoreDNS hop works."
    )


# --- 3. the monitor that measures liveness instead of function --------------


def _dns_monitors() -> list[dict]:
    return [m for m in _seed() if m.get("type") == "dns"]


def test_a_dns_monitor_watches_the_resolver_itself():
    """ICMP to the host is not a measurement of DNS.

    `infra-vpn-rpi4-tailscale` is a ping, and it stayed green throughout: the
    host was never down. The signal that would have fired within one interval is
    a resolution, so one has to exist.
    """
    monitors = _dns_monitors()
    assert monitors, (
        "no monitor of type `dns` exists in the seed. The rpi4 monitor is a ping, "
        "which measures that the host is up -- it was up for the entire outage. "
        "Nothing measured whether it resolves."
    )


@pytest.mark.parametrize("field", ["dns_resolve_server", "dns_resolve_type"])
def test_the_sync_can_actually_write_a_dns_monitors_own_fields(field: str):
    """A field the sync cannot write is a monitor that ships misconfigured.

    `WRITABLE_FIELDS` is the single declaration behind both the create payload
    and the diff ("compare exactly what you write"). A `dns` monitor whose
    resolver is absent from it would be created against Uptime Kuma's DEFAULT
    public resolver -- which cannot see a VPN-only staging zone, so the monitor
    would be permanently red and would be muted rather than fixed.
    """
    from toolkit.features.monitoring_diff import WRITABLE_FIELDS

    assert field in WRITABLE_FIELDS, (
        f"`{field}` is not writable, so a dns monitor would be created without it "
        "and would resolve against a public resolver that cannot see staging."
    )


def test_every_dns_monitor_resolves_against_our_own_resolver():
    """Pointing it at a public resolver would make it green for the wrong reason."""
    common = yaml.safe_load(COMMON.read_text())
    ours = {
        common["networking"]["nodes"]["rpi4"]["tailscale_ip"],
        common["networking"]["nodes"]["rpi4"]["lan_ip"],
    }
    for m in _dns_monitors():
        assert m.get("dns_resolve_server") in ours, (
            f"monitor {m.get('key')!r} resolves against {m.get('dns_resolve_server')!r}, "
            f"which is not one of rpi4's own addresses {sorted(ours)}. A public "
            "resolver answers for prod names and cannot see staging at all, so the "
            "monitor would report on something other than our resolver."
        )
