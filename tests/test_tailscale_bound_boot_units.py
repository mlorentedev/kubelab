"""A stack published on a node's Tailscale address must come back serving after a boot.

#2500. Two ways it comes back running and serving nothing:

1. dockerd resurrects the container through `restart: unless-stopped` before the
   address exists, and the bind is dropped. Plain `up -d` adopts that container,
   because the network attachment is not part of the compose spec hash
   (ANSIBLE-053, beelink). The repair is `--force-recreate` once the address exists.
2. The address arrives after the wait helper's bound. The unit fails in
   `ExecStartPre`, `ExecStart` never runs, and nothing re-runs a oneshot that
   failed at boot. Measured on 2026-10-26 after the lab moved site: every homelab
   node and rpi3 booted before the tailnet was reachable, and a day later rpi3's
   Uptime Kuma, bee's Gitea and every Glances were still up, healthy and attached
   to no network, their units `failed`. The repair is a retry, and a provision
   that starts a unit left failed.

The provision also compares the bindings each container asked for with the ones in
effect and recreates on a difference, through one shared task file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parent.parent
ROLES = REPO / "infra/ansible/roles"
DRIFT = REPO / "infra/ansible/playbooks/_includes/compose-port-drift.yml"
WAIT = "wait-for-tailscale-addr.sh"

#: The roles that bring up a compose stack bound to the Tailscale address, with
#: their stack unit and the task that starts the stack at provision.
STACKS = {
    "rpi3_services": ("kubelab-rpi3.service", "Start services"),
    "beelink_services": ("kubelab-compose.service", "Start services"),
    "glances": ("kubelab-glances.service", "Start Glances container"),
}


def _directives(path: Path) -> dict[str, list[str]]:
    """Values of each systemd directive, from executable lines only.

    The templates explain the race at length and the prose names the very flags
    asserted here, so a scan of the whole file is green whether or not a directive
    carries them.
    """
    out: dict[str, list[str]] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "[", "{#")):
            continue
        key, sep, value = stripped.partition("=")
        if sep:
            out.setdefault(key, []).append(value)
    return out


def _waiting_units() -> dict[str, dict[str, list[str]]]:
    """Every unit template that waits for an address before it runs."""
    units = {}
    for path in sorted(ROLES.glob("*/templates/*.service.j2")):
        directives = _directives(path)
        if any(WAIT in v for v in directives.get("ExecStartPre", [])):
            units[str(path.relative_to(ROLES))] = directives
    return units


UNITS = _waiting_units()


def test_every_known_stack_unit_is_found() -> None:
    """The checks below are only as wide as the discovery; an empty one passes them all."""
    found = {name.split("/")[0] for name in UNITS}
    assert set(STACKS) | {"agent_stack"} <= found, found


@pytest.mark.parametrize("name", sorted(UNITS))
def test_the_unit_recreates_the_stack(name: str) -> None:
    starts = [v for v in UNITS[name].get("ExecStart", []) if "compose" in v and " up" in v]
    assert starts, f"{name} no longer brings a stack up; drop it from this check"
    for value in starts:
        assert "--force-recreate" in value, (
            f"{name}: plain `up -d` adopts a container dockerd resurrected before the "
            "address existed, unbound and attached to no network"
        )


@pytest.mark.parametrize("name", sorted(UNITS))
def test_the_unit_retries_when_the_address_comes_late(name: str) -> None:
    directives = UNITS[name]
    assert directives.get("Restart") == ["on-failure"], (
        f"{name}: a oneshot that failed at boot is never run again, so an address that "
        "arrives after the wait's bound leaves the stack unbound until someone notices"
    )
    (delay,) = directives.get("RestartSec", ["0"])
    seconds = re.fullmatch(r"(\d+)s?", delay)
    # Under 30 s the retries can hit systemd's default start limit (5 in 10 s)
    # when the wait fails fast, and then the unit stops retrying for good.
    assert seconds and int(seconds.group(1)) >= 30, f"{name}: RestartSec={delay}"


def _drift(stdout: str, rc: int = 0) -> bool:
    (decide,) = [t for t in yaml.safe_load(DRIFT.read_text()) if "compose_port_drift" in (t.get("set_fact") or {})]
    expression = decide["set_fact"]["compose_port_drift"]
    env = ansible_env(str(DRIFT.parent))
    rendered = env.from_string(expression).render(
        _compose_port_drift_read={"rc": rc, "stdout_lines": stdout.splitlines()}
    )
    return rendered.strip() == "True"


@pytest.mark.parametrize(
    ("stdout", "rc", "expected"),
    [
        pytest.param("/uptime-kuma 1:0", 0, True, id="kuma-unbound"),  # measured on rpi3, 2026-10-26
        pytest.param("/gitea 2:0\n/github-runner 0:0", 0, True, id="gitea-unbound"),  # measured on bee, same day
        pytest.param("/gitea 2:2\n/github-runner 0:0", 0, False, id="stack-bound"),
        pytest.param("/uptime-kuma 1:1", 0, False, id="kuma-bound"),
        # It asks for no port, so none can be missing.
        pytest.param("/github-runner 0:0", 0, False, id="no-port-asked"),
        pytest.param("/gitea 12:0", 0, True, id="many-asked-none-bound"),
        pytest.param("/gitea 2:10", 0, False, id="more-bound-than-asked"),
        pytest.param("", 0, False, id="no-container-yet"),
        # The read failed: decide nothing from it.
        pytest.param("/uptime-kuma 1:0", 1, False, id="read-failed"),
    ],
)
def test_the_shared_check_finds_a_binding_never_established(stdout: str, rc: int, expected: bool) -> None:
    assert _drift(stdout, rc) is expected


def _tasks(role: str) -> list[dict]:
    return yaml.safe_load((ROLES / role / "tasks/main.yml").read_text())


@pytest.mark.parametrize("role", sorted(STACKS))
def test_the_provision_recreates_on_drift(role: str) -> None:
    _, start_name = STACKS[role]
    tasks = _tasks(role)
    names = [t.get("name") for t in tasks]
    imports = [
        i for i, t in enumerate(tasks) if str(t.get("import_tasks", "")).endswith("_includes/compose-port-drift.yml")
    ]
    assert len(imports) == 1, f"{role} must run the shared drift check once"
    start = names.index(start_name)
    assert imports[0] < start, f"{role}: the check must run before '{start_name}'"
    # A condition on an import lands on every task it imports, so the check could
    # be switched off while it still reads as present.
    assert "when" not in tasks[imports[0]], f"{role}: the drift check must run unconditionally"
    vars_ = tasks[imports[0]].get("vars", {})
    assert vars_.get("compose_port_drift_file", "").endswith("/compose.yml"), vars_
    command = str(tasks[start]["command"])
    assert "--force-recreate" in command and "compose_port_drift | bool" in command, (
        f"{role}: '{start_name}' must recreate when the check found drift: {command}"
    )


@pytest.mark.parametrize("role", sorted(STACKS))
def test_the_provision_starts_the_stack_unit(role: str) -> None:
    """Enabling a unit does not start it, so a unit that failed at boot stays failed."""
    unit, _ = STACKS[role]
    started = [
        t
        for t in _tasks(role)
        if (t.get("systemd") or t.get("ansible.builtin.systemd") or {}).get("name") == unit
        and (t.get("systemd") or t.get("ansible.builtin.systemd") or {}).get("state") == "started"
    ]
    assert started, f"{role}: no task starts {unit}"
