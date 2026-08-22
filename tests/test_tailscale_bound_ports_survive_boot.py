"""Binding a published port to a Tailscale address is a boot-order dependency.

#959 established the rule that a published port is governed by its bind address
and nothing else, because Docker's DNAT is evaluated before ufw's filter chains
and DOCKER-USER is empty fleet-wide. The remedy it prescribes -- bind to
`{{ tailscale_ip }}` instead of publishing bare -- is correct about reachability
and introduces a SECOND problem it does not mention.

At boot, Docker restores containers under `restart: unless-stopped`. tailscaled
comes up independently. If Docker gets there first, the bind to the Tailscale
address fails, and a failed bind drops that container's ENTIRE port publication
-- not just the one port. `restart: unless-stopped` does not help: the container
is running, so there is nothing to restart. It simply serves nothing.

Measured on rpi4, 2026-08-22: CoreDNS came back with NO published ports at all
after a reboot, including the `5353:53` that Pi-hole forwards to. Staging DNS was
dead for roughly ninety minutes and three separate green signals covered it.

TWO REMEDIES ARE VALID, and a role must use one of them:

1. **Bind to an address that exists before Docker starts** -- a LAN address on a
   physical interface. No race to lose. This is what `coredns` does, because
   rpi4 has a LAN address (`networking.nodes.rpi4.lan_ip`).

2. **Order the start after the address exists** -- a systemd oneshot with
   `After=tailscaled.service` and `ExecStartPre=wait-for-tailscale-addr.sh`.
   This is what `beelink_services` and `glances` already do, and it is the only
   option for a node with no LAN address (rpi3 is not on 172.16.1.0/24).

What must never happen again is a THIRD case: a Tailscale-bound port with
neither remedy. That is what this guard forbids, fleet-wide, so the next role
to follow #959's advice cannot silently inherit the race.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "infra/ansible/roles"

# A published-port line whose HOST side is a Jinja variable naming a Tailscale
# address. Matches `- "{{ tailscale_ip }}:8080:8080"` and the `node_ips.<node>`
# form, which deploy-dns.yml populates from `*.tailscale_ip`.
_TS_BOUND_PORT = re.compile(
    r'^\s*-\s*"\{\{\s*(?P<var>tailscale_ip|node_ips\.\w+)\s*\}\}:[^"]*"',
    re.MULTILINE,
)

# The two halves of remedy 2. Both are required: `After=` alone only orders
# against the unit STARTING, which is not the same as the address EXISTING.
_ORDERED_AFTER_TAILSCALED = re.compile(r"^After=.*\btailscaled\.service\b", re.MULTILINE)
_WAITS_FOR_ADDRESS = re.compile(r"wait-for-tailscale-addr\.sh")


def _compose_templates() -> list[Path]:
    return sorted(
        p
        for p in ROLES.rglob("*.j2")
        if "compose" in p.name.lower() and "service" not in p.name.lower()
    )


def _roles_binding_tailscale() -> list[tuple[str, Path, list[str]]]:
    out = []
    for tpl in _compose_templates():
        hits = [m.group(0).strip() for m in _TS_BOUND_PORT.finditer(tpl.read_text())]
        if hits:
            role = tpl.relative_to(ROLES).parts[0]
            out.append((role, tpl, hits))
    return out


def _role_has_boot_ordering(role: str) -> bool:
    """Does any unit template in this role implement remedy 2, fully?"""
    role_dir = ROLES / role
    for unit in role_dir.rglob("*.service.j2"):
        text = unit.read_text()
        if _ORDERED_AFTER_TAILSCALED.search(text) and _WAITS_FOR_ADDRESS.search(text):
            return True
    return False


def test_the_scan_finds_compose_templates_at_all():
    """A regex that silently matches nothing would make every test below vacuous."""
    templates = _compose_templates()
    assert len(templates) >= 3, (
        f"only found {len(templates)} compose templates under {ROLES}; the scan is "
        "probably not looking where the roles actually live"
    )


def test_the_scan_still_recognises_a_tailscale_bound_port():
    """Guard the guard: if the port syntax changes, this must fail rather than pass empty.

    Without this, a change to how ports are written would make
    `_roles_binding_tailscale()` return nothing and every role would trivially
    pass -- the exact shape of failure this whole file exists to prevent.
    """
    found = _roles_binding_tailscale()
    assert found, (
        "no Tailscale-bound published port found anywhere in the fleet. That is "
        "either a real (and welcome) change, or the regex stopped matching. "
        "Verify by hand before deleting this assertion."
    )


@pytest.mark.parametrize("role", sorted({r for r, _, _ in _roles_binding_tailscale()}))
def test_a_tailscale_bound_port_is_ordered_after_the_address_exists(role: str):
    """Remedy 2 is mandatory once remedy 1 is declined.

    A role that binds to a Tailscale address has chosen an address that does not
    exist yet at Docker-start time. It must therefore not start until it does.
    """
    offenders = [hits for r, _, hits in _roles_binding_tailscale() if r == role]
    assert _role_has_boot_ordering(role), (
        f"role {role!r} binds published ports to a Tailscale address:\n  "
        + "\n  ".join(h for group in offenders for h in group)
        + "\n\nbut has no systemd unit that both orders `After=tailscaled.service` "
        "and runs `wait-for-tailscale-addr.sh`. At boot Docker will race "
        "tailscaled; when it wins, the bind fails and the container loses ALL its "
        "published ports while still reporting `running`.\n\n"
        "Either bind to the node's LAN address (as `coredns` does), or copy the "
        "unit `beelink_services` and `glances` already use."
    )


def test_the_wait_script_the_units_reference_actually_exists():
    """A unit referencing a missing script fails at boot, which is the worst time."""
    script = REPO_ROOT / "infra/ansible/playbooks/files/wait-for-tailscale-addr.sh"
    assert script.is_file(), (
        f"{script} is missing, but service templates reference it in ExecStartPre. "
        "Every node using remedy 2 would fail to start its stack at boot."
    )
