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

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parent.parent
ROLES = REPO / "infra/ansible/roles"
DRIFT = REPO / "infra/ansible/playbooks/_includes/compose-port-drift.yml"
WAIT = "wait-for-tailscale-addr.sh"

#: The roles that bring up a compose stack bound to the Tailscale address, with
#: their stack unit and the task that starts the stack at provision, for the
#: roles that use the shared drift check.
STACKS = {
    "rpi3_services": ("kubelab-rpi3.service", "Start services"),
    "beelink_services": ("kubelab-compose.service", "Start services"),
    "glances": ("kubelab-glances.service", "Start Glances container"),
}

#: Every role's stack unit. agent_stack keeps its own drift check, which also
#: compares memory limits and networks, so it is not in STACKS.
UNITS_BY_ROLE = {role: unit for role, (unit, _) in STACKS.items()} | {
    "agent_stack": "agent-stack-webui.service",
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
    assert set(UNITS_BY_ROLE) <= found, found


@pytest.mark.parametrize("name", sorted(UNITS))
def test_the_unit_stays_active_after_it_ran(name: str) -> None:
    """Without it the unit goes inactive once ExecStart exits, and the provision's
    `state: started` would recreate a healthy stack on every run."""
    assert UNITS[name].get("Type") == ["oneshot"], name
    assert UNITS[name].get("RemainAfterExit") == ["yes"], name


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


@pytest.mark.parametrize("name", sorted(UNITS))
def test_only_the_wait_is_retried(name: str) -> None:
    """A compose error of its own must fail the unit, not recreate the stack every 30 s.

    systemd reads this against ExecStart's exit status only, so an ExecStartPre
    (the wait) that fails still retries. Measured on systemd 259, 2026-10-26.
    """
    assert UNITS[name].get("RestartPreventExitStatus") == ["1"], name


def test_every_stack_on_the_tailnet_address_waits_for_it() -> None:
    """A new stack that publishes on the address but has no waiting unit would
    pass every check above, which only sees units that already wait."""
    publishing = {
        path.relative_to(ROLES).parts[0]
        for path in ROLES.glob("*/templates/*compose*.j2")
        if "tailscale_ip }}:" in path.read_text()
    }
    assert publishing, "no compose template publishes on the address; the glob is stale"
    waiting = {name.split("/")[0] for name in UNITS}
    assert publishing <= waiting, f"publish on the address with no unit that waits for it: {publishing - waiting}"


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


#: `docker`, as far as the drift check asks it. `inspect` fills in only the fields
#: it knows and refuses any other, so a format that reads the wrong field, or in
#: the wrong order, produces lines the check must then judge.
DOCKER_STUB = """#!/usr/bin/env python3
import json, os, sys
containers = json.loads(os.environ["STUB_CONTAINERS"])
args = sys.argv[1:]
if args[0] == "compose":
    if "-q" not in args:
        print("NAME  IMAGE  STATUS")
    status = args[args.index("--status") + 1] if "--status" in args else None
    for c in containers:
        if status in (None, c["status"]):
            print(c["id"] if "-q" in args else c["name"])
elif args[0] == "inspect":
    fmt = args[args.index("--format") + 1]
    ids = args[args.index("--format") + 2:]
    if not ids:
        sys.exit('"docker inspect" requires at least 1 argument.')
    for i in ids:
        c = next(c for c in containers if c["id"] == i)
        line = (fmt.replace("{{.Name}}", "/" + c["name"])
                   .replace("{{len .HostConfig.PortBindings}}", str(c["asked"]))
                   .replace("{{len .NetworkSettings.Ports}}", str(c["bound"])))
        if "{{" in line:
            sys.exit("unknown field in " + fmt)
        print(line)
else:
    sys.exit("unexpected docker call: " + " ".join(args))
"""


def _drift_tasks() -> list[dict]:
    return yaml.safe_load(DRIFT.read_text())


def _run_read(containers: list[dict[str, Any]], tmp_path: Path) -> tuple[int, str]:
    """Render the read task as Ansible would and run it against the stub."""
    (read,) = [t for t in _drift_tasks() if t.get("register") == "_compose_port_drift_read"]
    command = (
        ansible_env(str(DRIFT.parent))
        .from_string(read["shell"])
        .render(compose_port_drift_file="/opt/stack/compose.yml")
    )
    stub = tmp_path / "docker"
    stub.write_text(DOCKER_STUB)
    stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "STUB_CONTAINERS": json.dumps(containers)}
    result = subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True, env=env, check=False)
    return result.returncode, result.stdout


def _container(name: str, status: str, asked: int, bound: int) -> dict[str, Any]:
    return {"id": f"id-{name}", "name": name, "status": status, "asked": asked, "bound": bound}


@pytest.mark.parametrize(
    ("containers", "expected"),
    [
        pytest.param([_container("uptime-kuma", "running", 1, 0)], True, id="kuma-unbound"),
        pytest.param(
            [_container("gitea", "running", 2, 0), _container("github-runner", "running", 0, 0)],
            True,
            id="gitea-unbound",
        ),
        pytest.param([_container("uptime-kuma", "running", 1, 1)], False, id="kuma-bound"),
        # A stopped or crash-looping container has no ports in effect for a reason
        # of its own; recreating the whole stack would not fix it.
        pytest.param(
            [_container("uptime-kuma", "running", 1, 1), _container("old", "exited", 1, 0)],
            False,
            id="stopped-container",
        ),
        pytest.param(
            [_container("gitea", "running", 2, 2), _container("act-runner", "restarting", 1, 0)],
            False,
            id="restarting-container",
        ),
        pytest.param([], False, id="nothing-running"),
    ],
)
def test_the_read_feeds_the_check_what_it_expects(
    containers: list[dict[str, Any]], expected: bool, tmp_path: Path
) -> None:
    """The expression is only as good as the lines the shell task gives it."""
    rc, stdout = _run_read(containers, tmp_path)
    assert _drift(stdout, rc) is expected, (rc, stdout)


def test_the_read_runs_in_a_dry_run() -> None:
    """In check mode a skipped read registers no stdout, and the check decides nothing."""
    (read,) = [t for t in _drift_tasks() if t.get("register") == "_compose_port_drift_read"]
    assert read.get("check_mode") is False


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


def _all_tasks(tasks: list[dict]) -> list[dict]:
    """Tasks at any depth: agent_stack nests its Open WebUI tasks in a block."""
    out = []
    for task in tasks:
        out.append(task)
        for key in ("block", "rescue", "always"):
            out.extend(_all_tasks(task.get(key) or []))
    return out


def _unit_starts(role: str) -> list[dict]:
    unit = UNITS_BY_ROLE[role]
    return [
        t
        for t in _all_tasks(_tasks(role))
        if (t.get("systemd") or t.get("ansible.builtin.systemd") or {}).get("name") == unit
        and (t.get("systemd") or t.get("ansible.builtin.systemd") or {}).get("state") == "started"
    ]


@pytest.mark.parametrize("role", sorted(UNITS_BY_ROLE))
def test_the_provision_starts_the_stack_unit(role: str) -> None:
    """Enabling a unit does not start it, so a unit that failed at boot stays failed."""
    assert _unit_starts(role), f"{role}: no task starts {UNITS_BY_ROLE[role]}"


@pytest.mark.parametrize("role", sorted(UNITS_BY_ROLE))
def test_the_unit_start_runs_outside_a_dry_run(role: str) -> None:
    """A condition can switch the task off while it still reads as present."""
    env = ansible_env(str(ROLES))
    facts = {"ansible_check_mode": False, "_rpi3_unit_file": {"stat": {"exists": True}}}
    for task in _unit_starts(role):
        conditions = task.get("when", [])
        for condition in conditions if isinstance(conditions, list) else [conditions]:
            rendered = env.from_string(f"{{{{ ({condition}) | bool }}}}").render(**facts)
            assert rendered.strip() == "True", f"{role}: `when: {condition}` skips the start"
