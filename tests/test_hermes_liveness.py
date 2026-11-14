"""AI-013: local Hermes liveness through the existing notification fabric.

The probe is executed against a fake Docker CLI, so healthy/starting/unhealthy/missing
states and daemon failures are behavioral checks rather than template-string-only claims.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_agent_stack_role import _context
from tests.shells import BASH
from tests.test_hermes_config import HERMES, _render

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
SCRIPT = ROLE / "files/hermes-liveness.sh"
TASKS = ROLE / "tasks/hermes.yml"


def _gateway() -> dict:
    return yaml.safe_load(_render("compose-hermes.yml.j2"))["services"]["hermes"]


def _walk(items):
    for item in items:
        yield item
        for key in ("block", "rescue", "always"):
            yield from _walk(item.get(key, []))


def _hermes_tasks() -> list[dict]:
    return list(_walk(yaml.safe_load(TASKS.read_text(encoding="utf-8"))))


def _task(name: str) -> dict:
    [task] = [task for task in _hermes_tasks() if task.get("name") == name]
    return task


def test_healthcheck_uses_bounded_simple_health_without_credentials() -> None:
    health = _gateway()["healthcheck"]
    command = " ".join(str(part) for part in health["test"])
    assert health["test"][:2] == ["CMD", "python"]
    assert "http://127.0.0.1:8642/health" in command
    assert "urllib.request" in command and "timeout=5" in command
    assert "detailed" not in command and "API_SERVER_KEY" not in command
    assert health["interval"] == "30s"
    assert health["timeout"] == "10s"
    assert health["retries"] == 3
    assert health["start_period"] == "60s"


def test_simple_health_does_not_turn_provider_readiness_into_liveness() -> None:
    command = " ".join(_gateway()["healthcheck"]["test"])
    assert command.rstrip().endswith("/health'") or "/health'" in command
    assert "/health/detailed" not in command
    assert "slack" not in command.lower() and "readiness" not in command.lower()


def test_notification_hooks_and_recovery_use_the_fleet_fabric() -> None:
    unit = _render("agent-stack-hermes-watchdog.service.j2")
    assert "OnFailure=kubelab-notify@%n.service" in unit
    assert "OnSuccess=kubelab-notify-recovered@%n.service" in unit
    assert "Type=oneshot" in unit
    assert f"User={HERMES['user']}" in unit
    uid = _context()["_agent_stack_agent_uid"]
    assert f"Environment=DOCKER_HOST=unix:///run/user/{uid}/docker.sock" in unit
    assert "NoNewPrivileges=yes" in unit and "ProtectSystem=strict" in unit
    # A read-only bind of a Unix socket rejects connect(2), not just file writes.
    assert f"ReadWritePaths=/run/user/{uid}/docker.sock" in unit


def test_unexpected_agent_manager_death_cannot_disable_its_own_detector() -> None:
    unit = _render("agent-stack-hermes-watchdog.service.j2")
    timer = _render("agent-stack-hermes-watchdog.timer.j2")
    assert "agent-stack-egress" not in unit
    assert "agent-stack-egress" not in timer


def test_timer_interval_and_boot_grace_match_the_contract() -> None:
    timer = _render("agent-stack-hermes-watchdog.timer.j2")
    assert "OnUnitActiveSec=2min" in timer
    assert "OnBootSec=10min" in timer
    assert "WantedBy=timers.target" in timer


def test_on_demand_timer_never_catches_up_a_powered_off_node() -> None:
    timer = _render("agent-stack-hermes-watchdog.timer.j2")
    assert not re.search(r"(?m)^Persistent\s*=", timer)
    assert not re.search(r"(?m)^OnCalendar\s*=", timer)


def test_no_external_monitor_or_always_on_dependency_is_added() -> None:
    monitors = json.loads((REPO / "infra/config/uptime-kuma/monitors.json").read_text(encoding="utf-8"))
    assert "agent-stack-hermes-watchdog" not in json.dumps(monitors)
    combined = _render("agent-stack-hermes-watchdog.service.j2") + _render(
        "agent-stack-hermes-watchdog.timer.j2"
    )
    assert "uptime" not in combined.lower() and "kuma" not in combined.lower()


@pytest.fixture
def run_probe(tmp_path: Path):
    def run(status: str, *, docker_rc: int = 0, name: str = "hermes-kubelab") -> subprocess.CompletedProcess[str]:
        docker = tmp_path / "docker"
        docker.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" > \"$FAKE_DOCKER_ARGS\"\n"
            "printf '%s\\n' \"$FAKE_DOCKER_STATUS\"\n"
            "exit \"$FAKE_DOCKER_RC\"\n",
            encoding="utf-8",
            newline="\n",
        )
        docker.chmod(0o755)
        args = tmp_path / "args"
        env = {
            **os.environ,
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "FAKE_DOCKER_STATUS": status,
            "FAKE_DOCKER_RC": str(docker_rc),
            "FAKE_DOCKER_ARGS": str(args),
        }
        result = subprocess.run(
            [BASH, str(SCRIPT), name],
            env=env,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=10,
            check=False,
        )
        result.fake_args = args.read_text(encoding="utf-8") if args.exists() else ""  # type: ignore[attr-defined]
        return result

    return run


@pytest.mark.parametrize("status", ["healthy"])
def test_probe_accepts_only_healthy(status: str, run_probe) -> None:
    result = run_probe(status)
    assert result.returncode == 0, result.stderr
    assert ".State.Health.Status" in result.fake_args


@pytest.mark.parametrize("status", ["starting", "unhealthy", "missing", ""])
def test_probe_fails_closed_for_non_healthy_health(status: str, run_probe) -> None:
    result = run_probe(status)
    assert result.returncode != 0
    assert status in result.stderr or "not healthy" in result.stderr


def test_probe_fails_when_the_rootless_docker_daemon_cannot_answer(run_probe) -> None:
    result = run_probe("", docker_rc=1)
    assert result.returncode != 0


@pytest.mark.parametrize("name", ["--help", "bad;name", "bad name", ""])
def test_probe_rejects_an_option_or_arbitrary_container_name(name: str, run_probe) -> None:
    result = run_probe("healthy", name=name)
    assert result.returncode == 64
    assert result.fake_args == "", "validation must happen before invoking Docker"


def test_activation_order_waits_for_gateway_health_before_starting_the_watcher() -> None:
    names = [task.get("name") for task in _hermes_tasks()]
    assert names.index("Enable the Hermes liveness timer") > names.index("Verify the Hermes API answers with its key")
    assert names.index("Enable the Hermes liveness timer") > names.index("Verify the gateway is connected to Slack")
    timer = _task("Enable the Hermes liveness timer")["ansible.builtin.systemd"]
    assert timer["enabled"] is True and timer["state"] == "started"


def test_unconfigured_hermes_stops_watching_before_taking_the_gateway_down() -> None:
    names = [task.get("name") for task in _hermes_tasks()]
    assert names.index("Disable the Hermes liveness timer") < names.index("Take the previous hermes-kubelab down")
    disable = _task("Disable the Hermes liveness timer")
    assert disable["ansible.builtin.systemd"]["enabled"] is False
    assert disable["ansible.builtin.systemd"]["state"] == "stopped"
    remove = _task("Remove the Hermes liveness units")
    assert remove["ansible.builtin.file"]["state"] == "absent"
