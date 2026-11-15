"""AI-013: local Hermes liveness through the existing notification fabric.

The probe is executed against a fake Docker CLI, so healthy/starting/unhealthy/missing
states and daemon failures are behavioral checks rather than template-string-only claims.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
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

def _probe_shell_has_python3() -> bool:
    return (
        subprocess.run(
            [BASH, "-c", "command -v python3"],
            env={**os.environ, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            timeout=5,
            check=False,
        ).returncode
        == 0
    )


requires_python3 = pytest.mark.skipif(
    not _probe_shell_has_python3(),
    reason="starting-state behavior needs python3 inside the probe shell",
)


def test_python3_gate_uses_the_probe_shell_not_the_host(monkeypatch) -> None:
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert not _probe_shell_has_python3()
    assert observed["command"] == [BASH, "-c", "command -v python3"]
    assert observed["env"]["PATH"] == "/usr/bin:/bin"


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
    assert health["test"][:2] == ["CMD", "python3"]
    assert "http://127.0.0.1:8642/health" in command
    assert "urllib.request" in command and "timeout=5" in command
    assert "detailed" not in command and "API_SERVER_KEY" not in command
    assert health["interval"] == "30s"
    assert health["timeout"] == "10s"
    assert health["retries"] == 3
    assert health["start_period"] == "60s"


def test_simple_health_does_not_turn_provider_readiness_into_liveness() -> None:
    command = " ".join(_gateway()["healthcheck"]["test"])
    assert "urlopen('http://127.0.0.1:8642/health', timeout=5)" in command
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
    # ProtectHome=yes hides /run/user entirely; read-only plus one RW socket
    # preserves home confinement without hiding the daemon endpoint.
    assert "ProtectHome=read-only" in unit
    assert not re.search(r"(?m)^ProtectHome=(yes|true)$", unit)
    assert f"ReadWritePaths=/run/user/{uid}/docker.sock" in unit


def test_unexpected_agent_manager_death_cannot_disable_its_own_detector() -> None:
    unit = _render("agent-stack-hermes-watchdog.service.j2")
    timer = _render("agent-stack-hermes-watchdog.timer.j2")
    assert "agent-stack-egress" not in unit
    assert "agent-stack-egress" not in timer
    combined = unit + timer
    for directive in ("Requires", "Requisite", "BindsTo", "PartOf", "ConditionActive"):
        assert not re.search(rf"(?m)^{directive}=", combined)


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
    def run(
        status: str,
        *,
        docker_rc: int = 0,
        name: str = "hermes-kubelab",
        running: bool = True,
        started_at: datetime | None = None,
        restart_count: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        docker = tmp_path / "docker"
        docker.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" > \"$FAKE_DOCKER_ARGS\"\n"
            "printf '%s|%s|%s|%s\\n' \"$FAKE_DOCKER_STATUS\" \"$FAKE_DOCKER_RUNNING\" "
            "\"$FAKE_DOCKER_STARTED_AT\" \"$FAKE_DOCKER_RESTART_COUNT\"\n"
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
            "FAKE_DOCKER_RUNNING": "true" if running else "false",
            "FAKE_DOCKER_STARTED_AT": (started_at or datetime.now(UTC)).isoformat(),
            "FAKE_DOCKER_RESTART_COUNT": str(restart_count),
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
    assert ".State.StartedAt" in result.fake_args
    assert ".RestartCount" in result.fake_args
    assert ".State.RestartCount" not in result.fake_args


@pytest.mark.parametrize(
    "status",
    [pytest.param("starting", marks=requires_python3), "unhealthy", "missing", ""],
)
def test_probe_fails_closed_for_non_healthy_health(status: str, run_probe) -> None:
    # `starting` is sustained here; the bounded recent-start grace is tested below.
    started_at = datetime.now(UTC) - timedelta(minutes=5) if status == "starting" else None
    result = run_probe(status, started_at=started_at)
    assert result.returncode != 0
    assert "not healthy" in result.stderr
    if status:
        assert status in result.stderr


@requires_python3
@pytest.mark.parametrize("restart_count", [0, 1])
def test_probe_graces_one_recent_gateway_start(restart_count: int, run_probe) -> None:
    result = run_probe("starting", restart_count=restart_count)
    assert result.returncode == 0, result.stderr


@requires_python3
def test_probe_graces_a_start_inside_the_full_compose_window(run_probe) -> None:
    # Leave subprocess startup headroom; the exact 150s rejection is tested below.
    result = run_probe("starting", started_at=datetime.now(UTC) - timedelta(seconds=140))
    assert result.returncode == 0, result.stderr


@requires_python3
def test_probe_rejects_sustained_starting(run_probe) -> None:
    result = run_probe("starting", started_at=datetime.now(UTC) - timedelta(seconds=150))
    assert result.returncode != 0


@requires_python3
def test_probe_rejects_a_repeated_crash_loop_even_inside_the_grace(run_probe) -> None:
    result = run_probe("starting", restart_count=2)
    assert result.returncode != 0


@requires_python3
def test_probe_rejects_starting_when_the_container_is_not_running(run_probe) -> None:
    result = run_probe("starting", running=False)
    assert result.returncode != 0


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
    assert names.index("Enable the Hermes liveness timer") > names.index("Install the Hermes liveness probe")
    assert names.index("Enable the Hermes liveness timer") > names.index("Install the Hermes liveness units")
    assert names.index("Enable the Hermes liveness timer") > names.index(
        "Wait for the Hermes healthcheck to report healthy"
    )
    wait = _task("Wait for the Hermes healthcheck to report healthy")
    assert wait["become"] is True
    assert any(".State.Health.Status" in str(part) for part in wait["ansible.builtin.command"]["argv"])
    assert "_agent_stack_hermes_docker_health.stdout == 'healthy'" in wait["until"]
    assert wait["retries"] * wait["delay"] >= 150
    timer = _task("Enable the Hermes liveness timer")["ansible.builtin.systemd"]
    assert timer["enabled"] is True and timer["state"] == "started"


def test_failed_recreation_restores_a_paused_timer_and_preserves_the_failure() -> None:
    deploy = next(task for task in yaml.safe_load(TASKS.read_text(encoding="utf-8")) if task.get("name") == "Deploy hermes-kubelab")
    restore = deploy["always"][0]
    assert restore["name"] == "Restore the Hermes liveness timer after deployment"
    assert restore["ansible.builtin.systemd"]["enabled"] is True
    assert restore["ansible.builtin.systemd"]["state"] == "started"
    assert "_agent_stack_hermes_watchdog_paused" in restore["when"]
    assert deploy["rescue"][-1]["name"] == "Propagate the failed Hermes deployment"
    assert "ansible.builtin.fail" in deploy["rescue"][-1]


def test_recreation_pauses_an_existing_timer_without_disabling_it() -> None:
    names = [task.get("name") for task in _hermes_tasks()]
    pause_name = "Pause the Hermes liveness timer during gateway recreation"
    assert names.index(pause_name) < names.index("Start hermes-kubelab")
    pause = _task(pause_name)
    assert "_agent_stack_hermes_recreate_expected" in pause["when"]
    assert pause["ansible.builtin.systemd"]["state"] == "stopped"
    assert "enabled" not in pause["ansible.builtin.systemd"], "a later provision must re-enable it without drift"
    assert names.index("Enable the Hermes liveness timer") > names.index(
        "Wait for the Hermes healthcheck to report healthy"
    )
    recreate = _task("Hold whether the rendered inputs will recreate Hermes")["ansible.builtin.set_fact"]
    expression = str(recreate["_agent_stack_hermes_recreate_expected"])
    for registered in ("compose", "config", "env_file", "plugins_copy", "ts_env_file", "unbound"):
        assert registered in expression
    assert "--force-recreate' if _agent_stack_hermes_recreate_expected" in str(
        _task("Start hermes-kubelab")["ansible.builtin.command"]
    )


def test_unconfigured_hermes_stops_watching_before_taking_the_gateway_down() -> None:
    names = [task.get("name") for task in _hermes_tasks()]
    assert names.index("Disable the Hermes liveness timer") < names.index("Take the previous hermes-kubelab down")
    disable = _task("Disable the Hermes liveness timer")
    assert disable["ansible.builtin.systemd"]["enabled"] is False
    assert disable["ansible.builtin.systemd"]["state"] == "stopped"
    remove = _task("Remove the Hermes liveness units")
    assert remove["ansible.builtin.file"]["state"] == "absent"
    assert remove["ansible.builtin.file"]["path"] == "{{ item }}"
    assert "/etc/systemd/system/agent-stack-hermes-watchdog.timer" in remove["loop"]
    assert "/etc/systemd/system/agent-stack-hermes-watchdog.service" in remove["loop"]
    assert "{{ agent_stack_vault_libexec }}/hermes-liveness.sh" in remove["loop"]
