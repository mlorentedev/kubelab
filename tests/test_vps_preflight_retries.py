"""The VPS pre-flight survives one slow packet and still fails fast on a dead VPS.

`_includes/check-vps-reachable.yml` ran `ssh -o ConnectTimeout=5` once, so the first
connection over a cold tailnet path that took longer than 5 s refused a whole provision
of bee on 2026-10-26; a retry seconds later answered in 431 ms. The check now retries.

Two things have to hold at once, and they pull against each other: enough attempts that a
cold path warms up, and a worst case short enough that an unreachable VPS fails the run
promptly instead of stalling it. The first is exercised against the real include with a
stand-in `ssh`; the second is arithmetic over the declared numbers.

Ansible counts `retries` as attempts AFTER the first (`task_executor.py`: `retries = 1`,
then `+= task.retries`), so N retries is N + 1 attempts. The bound below uses that.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
INCLUDE = REPO / "infra/ansible/playbooks/_includes/check-vps-reachable.yml"
CI = REPO / ".github/workflows/ci.yml"

#: "Well under a minute": the unreachable case must give up inside this many seconds.
WORST_CASE_SECONDS = 45


def _check_task() -> dict[str, Any]:
    tasks = yaml.safe_load(INCLUDE.read_text(encoding="utf-8"))
    (task,) = [t for t in tasks if "register" in t and "ansible.builtin.command" in t]
    return task


def _connect_timeout(task: dict[str, Any]) -> int:
    match = re.search(r"ConnectTimeout=(\d+)", str(task["ansible.builtin.command"]))
    assert match, "the pre-flight must bound each connection with ConnectTimeout"
    return int(match.group(1))


def _stall_bound(task: dict[str, Any]) -> int:
    """Seconds an established session may go unanswered: ssh sends CountMax probes, one per Interval."""
    command = str(task["ansible.builtin.command"])
    interval = re.search(r"ServerAliveInterval=(\d+)", command)
    count = re.search(r"ServerAliveCountMax=(\d+)", command)
    assert interval and count, "ConnectTimeout does not bound a session that stalls after connecting"
    return int(interval.group(1)) * int(count.group(1))


def _worst_case_seconds(task: dict[str, Any]) -> int:
    """Every attempt connects late and then stalls, with the delay slept between attempts and not after the last."""
    attempts = int(task["retries"]) + 1
    per_attempt = _connect_timeout(task) + _stall_bound(task)
    return attempts * per_attempt + int(task["retries"]) * int(task["delay"])


class TestTheDeclaredRetry:
    def test_the_check_retries_until_ssh_answers(self) -> None:
        task = _check_task()
        assert int(task["retries"]) >= 1, "a single attempt is the defect"
        assert "_vps_check.rc == 0" in str(task["until"])

    def test_attempts_are_spaced_so_a_cold_path_can_warm(self) -> None:
        assert int(_check_task()["delay"]) >= 1

    def test_an_unreachable_vps_still_fails_in_well_under_a_minute(self) -> None:
        task = _check_task()
        assert _worst_case_seconds(task) <= WORST_CASE_SECONDS, (
            f"{task['retries'] + 1} attempts of {_connect_timeout(task)} s with {task['delay']} s between them"
        )

    def test_each_attempt_is_still_bounded_and_non_interactive(self) -> None:
        command = str(_check_task()["ansible.builtin.command"])
        assert "BatchMode=yes" in command
        assert _connect_timeout(_check_task()) <= 10
        assert 0 < _stall_bound(_check_task()) <= 10


class TestCiRunsTheEffectTests:
    """The effect tests skip where `ansible-playbook` is absent, and CI's `Tests` step has none.

    That step runs before Ansible is installed, so `make test` reports them as skipped and
    CI never reports that the retry was not exercised. A later step in the job that does
    install Ansible runs them, as it does for the zero-host test (#1228).
    """

    def _steps(self) -> list[dict[str, Any]]:
        return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["tests"]["steps"]

    def test_a_step_runs_this_file_after_ansible_is_installed(self) -> None:
        steps = self._steps()
        install = next(
            i for i, s in enumerate(steps) if "pip install" in str(s.get("run", "")) and "ansible-core" in str(s["run"])
        )
        runs = [i for i, s in enumerate(steps) if Path(__file__).name in str(s.get("run", ""))]
        assert runs, "no CI step runs this file where Ansible is installed: its effect tests skip silently"
        assert all(i > install for i in runs), "the step runs before ansible-core is installed, so the tests skip"


# --- the effect: run the real include against a stand-in ssh ---------------------------

STUB_SSH = """#!/bin/sh
# Answers like a VPS whose first FAIL_FIRST connections time out on a cold path.
n=$(cat "$STUB_DIR/count" 2>/dev/null || echo 0)
n=$((n + 1))
echo "$n" > "$STUB_DIR/count"
echo "$@" >> "$STUB_DIR/argv"
if [ "$n" -le "$FAIL_FIRST" ]; then
    echo "ssh: connect to host stub port 22: Connection timed out" >&2
    exit 255
fi
echo ok
"""

PLAY = """- hosts: localhost
  gather_facts: false
  connection: local
  tasks:
    - ansible.builtin.include_tasks: {include}
"""


def _run_preflight(tmp_path: Path, fail_first: int) -> tuple[subprocess.CompletedProcess[str], int, float]:
    """Run the real include; return the result, how often ssh was called, and the seconds taken."""
    # The include reads {{ playbook_dir }}/../../config/values/common.yaml, so the play sits
    # at <root>/ansible/playbooks and a minimal SSOT at <root>/config/values.
    playbooks = tmp_path / "ansible" / "playbooks"
    values = tmp_path / "config" / "values"
    playbooks.mkdir(parents=True)
    values.mkdir(parents=True)
    (values / "common.yaml").write_text(
        "networking:\n  vps:\n    tailscale_ip: stub-vps.example.invalid\n    ssh_user: stubuser\n",
        encoding="utf-8",
    )
    (playbooks / "play.yml").write_text(PLAY.format(include=INCLUDE), encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh = bin_dir / "ssh"
    ssh.write_text(STUB_SSH, encoding="utf-8")
    ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "STUB_DIR": str(tmp_path),
        "FAIL_FIRST": str(fail_first),
        "ANSIBLE_LOCALHOST_WARNING": "False",
        "ANSIBLE_NOCOLOR": "1",
    }
    started = time.monotonic()
    result = subprocess.run(
        ["ansible-playbook", str(playbooks / "play.yml"), "-i", "localhost,"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.monotonic() - started
    count_file = tmp_path / "count"
    calls = int(count_file.read_text().strip()) if count_file.exists() else 0
    return result, calls, elapsed


@pytest.mark.allow_host_clients(
    reason="runs ansible-playbook on localhost with a stand-in ssh that never leaves the machine"
)
def test_a_cold_path_that_times_out_once_does_not_fail_the_provision(tmp_path: Path) -> None:
    if shutil.which("ansible-playbook") is None:
        pytest.skip("ansible-playbook not on PATH: the retry was NOT executed")

    result, calls, _ = _run_preflight(tmp_path, fail_first=1)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == 2, "one timeout, then the answer"
    assert "stubuser@stub-vps.example.invalid" in (tmp_path / "argv").read_text()


@pytest.mark.allow_host_clients(
    reason="runs ansible-playbook on localhost with a stand-in ssh that never leaves the machine"
)
def test_a_vps_that_never_answers_fails_after_the_declared_attempts_and_says_why(tmp_path: Path) -> None:
    if shutil.which("ansible-playbook") is None:
        pytest.skip("ansible-playbook not on PATH: the retry was NOT executed")

    result, calls, elapsed = _run_preflight(tmp_path, fail_first=10_000)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert calls == int(_check_task()["retries"]) + 1
    assert elapsed < WORST_CASE_SECONDS
    assert "Connection timed out" in output, "the last ssh error must reach the operator"
