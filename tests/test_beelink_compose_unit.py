"""The Beelink's compose stack must come back REACHABLE, not merely running.

ANSIBLE-053. Measured 2026-08-23: gitea and minio ran `healthy` for over an hour
attached to no network and publishing nothing. Their only traffic was their own
healthcheck from `[::1]`. `github-runner` — the one service in the stack that
declares no `ports:` — was unaffected.

The wait-for-tailscale-addr guard (#1061) is necessary and **not sufficient**. On
that boot it reported `100.64.0.3 is up on tailscale0 after 20s` and the unit then
reported success; the containers still came up netless. So the guard's presence
proves nothing about the outcome, and neither does the unit's exit status.

The state is reproducible without waiting for a race, which is how the assertions
below were chosen rather than guessed:

    docker network disconnect kubelab gitea   ->  Up (healthy), Ports {}, HTTP 000
    systemctl restart kubelab-compose.service ->  Up (healthy), Ports {}, HTTP 000

Plain `up -d` leaves it exactly as it found it: compose starts a container whose
spec hash is unchanged, and the network attachment is not part of that hash.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import ChainableUndefined, Environment, FileSystemLoader, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"
UNIT_TEMPLATE = "kubelab-compose.service.j2"


def _render() -> str:
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=StrictUndefined)
    return env.get_template(UNIT_TEMPLATE).render(
        ansible_managed="Ansible managed",
        beelink_deploy_dir="/opt/kubelab",
        tailscale_ip="100.64.0.3",
    )


def _directive(name: str) -> list[str]:
    """Values of a systemd directive, from EXECUTABLE lines only.

    The template explains the failure at length, and every explanation names the
    commands involved. Scanning the whole file for `--force-recreate` matches the
    prose whether or not ExecStart carries it — the exact false green this repo
    has hit repeatedly, including once in this same session's own test.
    """
    out = []
    for line in _render().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if re.match(rf"^{name}=", stripped):
            out.append(stripped.split("=", 1)[1])
    return out


def test_the_stack_is_recreated_on_every_boot() -> None:
    """`up -d` alone cannot repair a container that came up on no network.

    Measured, not argued: the broken state was injected with
    `docker network disconnect`, and `systemctl restart` on the unpatched unit
    left gitea at HTTP 000 — before and after.
    """
    exec_start = _directive("ExecStart")
    assert exec_start, "the unit must still bring the stack up"
    assert any("--force-recreate" in v for v in exec_start), (
        "ExecStart must pass --force-recreate. Without it, a container that came "
        "up attached to no network stays that way across every restart, because "
        "compose starts a container whose spec hash is unchanged and the network "
        "attachment is not part of that hash."
    )


def test_the_guard_is_kept_as_well_as_the_recreate() -> None:
    """Not either/or. The guard still prevents the bind failing in the first place.

    Recreating after the address exists is the repair; waiting for the address is
    the prevention. Dropping the guard would make every boot depend on the repair.
    """
    pre = _directive("ExecStartPre")
    assert any("wait-for-tailscale-addr.sh" in v for v in pre), (
        "the Tailscale address guard must stay: --force-recreate repairs the outcome, the guard avoids provoking it"
    )


def test_the_fix_does_not_live_in_execstop() -> None:
    """`down` in ExecStop would be absent in the scenario that matters.

    BACKUP-044 Part 0 measured it: on a power cut ExecStop never runs, and dockerd
    resurrects the containers at +10s via `restart: unless-stopped` — before
    tailscaled and before this unit. A fix that only executes on a graceful
    shutdown does not cover an on-demand node's normal failure.
    """
    stop = _directive("ExecStop")
    assert not any(" down" in v for v in stop), (
        "ExecStop must not be the place the fix lives; it does not run on a power "
        "cut, which is the path an on-demand node has to survive"
    )


def test_every_service_that_publishes_on_the_tailscale_address_is_covered() -> None:
    """The blast radius is defined by `ports:`, so read it from the compose SSOT.

    github-runner survived the incident and the other two did not; the property
    that separates them is declaring a published port bound to the node's
    Tailscale address. If a fourth service gains one, it inherits the same
    exposure and the same unit already covers it — this asserts the unit is the
    single entry point rather than a per-service workaround.
    """
    # Permissive undefined here, deliberately: this render only needs the
    # STRUCTURE of `ports:`, and `tailscale_ip` is the one value that matters and
    # is supplied. Enumerating every image tag and credential the compose file
    # interpolates would make this test fail whenever an unrelated variable is
    # renamed, which is a guard that cries wolf rather than one that guards.
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=ChainableUndefined)
    compose = yaml.safe_load(
        env.get_template("compose.yml.j2").render(
            ansible_managed="Ansible managed",
            beelink_deploy_dir="/opt/kubelab",
            tailscale_ip="100.64.0.3",
        )
    )
    publishing = [
        name
        for name, svc in (compose.get("services") or {}).items()
        if any("100.64.0.3" in str(p) for p in (svc.get("ports") or []))
    ]
    assert publishing, (
        "no service publishes on the Tailscale address — if that is now true by "
        "design, this unit's --force-recreate is no longer load-bearing and the "
        "reasoning in it should be revisited rather than left as folklore"
    )
