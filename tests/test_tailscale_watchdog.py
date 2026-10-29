"""The edge's Tailscale watchdog is rendered by the tailscale role (#2675).

It was made by hand on the RPi4, with its own copy of the `tailscale up` flags and
no bound: on the hard-reset test of #2661 its `tailscale up` was still waiting
for the control server 10 minutes after boot, holding a start job, so the boot
never finished (lesson-653). The role renders it from the flags its own
`tailscale up` uses, minus the key, and bounds it below the timer's period.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.test_headscale_rejoin import (
    CONFIG,
    DEFAULTS,
    KEY,
    PLAYBOOKS,
    ROLE,
    TASKS,
    _play_vars,
    _render,
    _task,
    _up_command,
)

SERVICE = ROLE / "templates" / "tailscale-watchdog.service.j2"
TIMER = ROLE / "templates" / "tailscale-watchdog.timer.j2"


def _unit(path: Path, **facts: Any) -> dict[str, str]:
    text = _render(path.read_text(), ansible_managed="managed", **facts)
    return dict(line.split("=", 1) for line in text.splitlines() if re.match(r"^[A-Z]\w*=", line))


def _service(node: str = "rpi4", key: str = "") -> dict[str, str]:
    flags = _render(_task("Build the Tailscale up flags")["set_fact"]["tailscale_up_flags"], **_play_vars(node))
    return _unit(SERVICE, tailscale_up_flags=flags, _tailscale_key=key)


def _script(service: dict[str, str]) -> str:
    argv = shlex.split(service["ExecStart"])
    assert argv[:2] == ["/bin/sh", "-c"] and len(argv) == 3, service["ExecStart"]
    return argv[2]


def _watchdog_up(service: dict[str, str]) -> list[str]:
    match = re.search(r"exec (tailscale up .*?) --timeout=(\d+)s$", _script(service))
    assert match, "the watchdog must exec a bounded `tailscale up`"
    return match.group(1).split()


def test_the_watchdog_runs_the_roles_own_flags() -> None:
    """The flags the play declares reach the watchdog on the next provision, and
    `--reset` (tailscale/tailscale#5597) keeps it from refusing on a changed flag."""
    assert _watchdog_up(_service()) == _up_command("rpi4", "").split()
    assert "{{ tailscale_up_flags }}" in SERVICE.read_text()


def test_the_edge_watchdog_carries_every_flag_its_play_declares() -> None:
    command = _watchdog_up(_service())
    assert command[:3] == ["tailscale", "up", "--reset"]
    assert f"--login-server=https://{CONFIG['apps']['services']['core']['headscale']['domain']}" in command
    assert "--accept-dns=false" in command
    assert "--accept-routes=false" in command
    assert f"--advertise-routes={CONFIG['networking']['lan_cidr']}" in command


def test_the_watchdog_never_carries_a_key() -> None:
    """A rejoin run holds a minted key in its facts; none of it reaches the unit."""
    assert "authkey" not in " ".join(_service(key=KEY).values())
    assert "_tailscale_key" not in SERVICE.read_text()
    assert "tailscale_up_cmd" not in SERVICE.read_text()
    assert "authkey" not in _task("Build the Tailscale up flags")["set_fact"]["tailscale_up_flags"]


@pytest.mark.allow_host_clients(reason="`sh -n` parses the script and runs none of it")
def test_the_watchdog_acts_only_on_the_states_it_was_made_for() -> None:
    script = _script(_service())
    assert 'grep -qE "stopped|NeedsLogin|NoState" || exit 0;' in script
    assert subprocess.run(["sh", "-n", "-c", script], check=False).returncode == 0


def test_the_watchdog_is_bounded_below_its_period_and_not_restarted() -> None:
    """lesson-653: a oneshot holds a start job until its command exits."""
    service, timer = _service(), _unit(TIMER)
    assert service["Type"] == "oneshot"
    bound = int(service["TimeoutStartSec"])
    wait = int(re.search(r"--timeout=(\d+)s", service["ExecStart"]).group(1))
    assert wait < bound < int(timer["OnUnitActiveSec"])
    assert service.get("Restart", "no") == "no", "the timer is the retry"


def test_the_provision_starts_only_the_timer() -> None:
    """Starting the service would run `tailscale up` inside the provision."""
    install = _task("Install the Tailscale watchdog")
    assert install["loop"] == ["tailscale-watchdog.service", "tailscale-watchdog.timer"]
    assert install["template"]["dest"] == "/etc/systemd/system/{{ item }}"
    started = [t["systemd"]["name"] for t in TASKS if "state" in (t.get("systemd") or {})]
    assert started == ["tailscaled", "tailscale-watchdog.timer"]
    timer = _task("Enable and start the Tailscale watchdog timer")
    assert timer["systemd"]["daemon_reload"] is True
    assert "tailscale_watchdog | bool" in timer["when"]


def test_the_flags_are_built_before_the_command_that_uses_them() -> None:
    names = [t.get("name", "") for t in TASKS]
    assert names.index("Build the Tailscale up flags") < names.index("Build Tailscale up command")
    assert "{{ tailscale_up_flags }}" in _task("Build Tailscale up command")["set_fact"]["tailscale_up_cmd"]


def test_only_the_edge_turns_the_watchdog_on() -> None:
    assert DEFAULTS["tailscale_watchdog"] is False
    on = []
    for playbook in sorted(PLAYBOOKS.glob("*.yml")):
        for play in yaml.safe_load(playbook.read_text()) or []:
            for role in play.get("roles") or []:
                if isinstance(role, dict) and (role.get("vars") or {}).get("tailscale_watchdog"):
                    on.append(playbook.name)
    assert on == ["provision-rpi4.yml"]
