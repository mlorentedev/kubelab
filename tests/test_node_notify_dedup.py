"""A unit that keeps failing pages once, reminds hourly, and says when it recovers (#2423).

Runs the SHIPPED `kubelab-notify.sh` end to end with `systemctl`, `journalctl` and `curl`
replaced by shims on PATH: the claim is about what reaches the operator's phone, so the
test counts the requests the script makes, never the text that describes them.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from tests.test_node_notify_role import _defaults, _render

UNIT = "hermes-kubelab-vault-sync.service"
REMINDER = int(_defaults()["node_notify_reminder_seconds"])  # type: ignore[call-overload]
TTL = int(_defaults()["node_notify_state_ttl_seconds"])  # type: ignore[call-overload]


class Node:
    """A scratch directory standing in for one node: the rendered script, its state and its shims."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.sent = root / "sent.jsonl"
        self.result = root / "result"
        self.curl_exit = root / "curl-exit"
        (root / "bin").mkdir()
        (root / "secret").write_text("tok")
        script = _render(
            "kubelab-notify.sh.j2",
            node_notify_secret_file=str(root / "secret"),
            node_notify_state_dir=str(self.state),
        )
        self.script = root / "notify.sh"
        self.script.write_text(script)
        self.script.chmod(0o700)
        self._shim("systemctl", 'printf "Result=%s\\n" "$(cat "$NODE_RESULT")"')
        self._shim("journalctl", 'echo "unit output"')
        self._shim(
            "curl",
            'cat >/dev/null; d=""; while [ $# -gt 0 ]; do [ "$1" = -d ] && d="$2"; shift; done;'
            ' printf "%s\\n" "$d" >> "$NODE_SENT"; exit "$(cat "$NODE_CURL_EXIT" 2>/dev/null || echo 0)"',
        )
        self.set_result("exit-code")

    def _shim(self, name: str, body: str) -> None:
        path = self.root / "bin" / name
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def set_result(self, value: str) -> None:
        self.result.write_text(value)

    def run(self, *args: str, unit: str = UNIT) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
            "NODE_RESULT": str(self.result),
            "NODE_SENT": str(self.sent),
            "NODE_CURL_EXIT": str(self.curl_exit),
        }
        return subprocess.run(
            ["bash", str(self.script), *args, unit], capture_output=True, text=True, env=env, timeout=60
        )

    def titles(self) -> list[str]:
        if not self.sent.exists():
            return []
        return [json.loads(line)["title"] for line in self.sent.read_text().splitlines()]

    def age_state(self, seconds: int, unit: str = UNIT) -> None:
        """Pretend the last page went out `seconds` ago."""
        path = self.state / unit
        count, first, last = path.read_text().split()
        path.write_text(f"{count} {first} {int(last) - seconds}\n")


@pytest.fixture
def node(tmp_path: Path) -> Node:
    return Node(tmp_path)


def test_the_first_failure_pages(node: Node) -> None:
    assert node.run().returncode == 0
    assert len(node.titles()) == 1 and "failed" in node.titles()[0]


def test_the_second_consecutive_failure_sends_nothing(node: Node) -> None:
    node.run()
    assert node.run().returncode == 0
    assert len(node.titles()) == 1, "the 2nd identical failure paged again"


def test_fifty_failures_in_an_hour_are_one_page(node: Node) -> None:
    for _ in range(50):
        node.run()
    assert len(node.titles()) == 1


def test_a_reminder_goes_out_once_the_interval_has_passed_and_carries_the_count(node: Node) -> None:
    node.run()
    node.run()
    node.age_state(REMINDER + 5)
    node.run()
    titles = node.titles()
    assert len(titles) == 2
    assert "still failing" in titles[1] and "3" in titles[1], titles[1]


def test_the_reminder_clock_restarts_after_a_reminder(node: Node) -> None:
    node.run()
    node.age_state(REMINDER + 5)
    node.run()
    node.run()
    assert len(node.titles()) == 2


def test_a_success_after_failures_sends_one_recovery_and_clears_the_state(node: Node) -> None:
    node.run()
    node.run()
    node.set_result("success")
    assert node.run("--recovered").returncode == 0
    titles = node.titles()
    assert len(titles) == 2 and "recovered" in titles[1] and "2" in titles[1], titles
    assert not (node.state / UNIT).exists()
    node.set_result("exit-code")
    node.run()
    assert "failed" in node.titles()[-1] and len(node.titles()) == 3, "a new incident pages again"


def test_a_success_with_nothing_failing_sends_nothing(node: Node) -> None:
    node.set_result("success")
    assert node.run("--recovered").returncode == 0
    assert node.titles() == [], "every healthy run of a recovery-wired unit would page"


def test_a_failed_delivery_does_not_count_as_a_page(node: Node) -> None:
    """If n8n is down the operator has heard nothing; the next failure must try again."""
    node.curl_exit.write_text("22")
    assert node.run().returncode != 0
    node.curl_exit.write_text("0")
    node.run()
    assert len(node.titles()) == 2, "a page that never arrived was treated as sent"


def test_a_stale_incident_is_a_new_incident(node: Node) -> None:
    """A unit nobody wired a recovery for must not report an old count as `still failing`."""
    node.run()
    node.age_state(TTL + 5)
    node.run()
    titles = node.titles()
    assert len(titles) == 2 and "still failing" not in titles[1], titles


def test_units_are_tracked_separately(node: Node) -> None:
    node.run()
    node.run(unit="node-backup-ship.service")
    assert len(node.titles()) == 2


def test_a_hand_invocation_for_a_healthy_unit_still_announces_itself_and_keeps_no_state(node: Node) -> None:
    node.set_result("success")
    node.run()
    node.run()
    assert len(node.titles()) == 2, "the delivery test must reach the phone every time it is run"
    assert not (node.state / UNIT).exists()


def test_a_corrupt_state_file_does_not_silence_the_unit(node: Node) -> None:
    node.state.mkdir()
    (node.state / UNIT).write_text("garbage\n")
    node.run()
    assert len(node.titles()) == 1


def test_the_state_outlives_the_reminder() -> None:
    """A failing unit refreshes its state each reminder; a ttl shorter than that would restart every incident."""
    assert TTL > REMINDER


def test_the_vault_sync_unit_closes_its_incidents() -> None:
    from tests.test_agent_stack_role import _environment, _resolved

    env = _environment()
    unit = env.get_template("vault-sync.service.j2").render(**_resolved(env))
    assert "OnFailure=kubelab-notify@%n.service" in unit
    assert "OnSuccess=kubelab-notify-recovered@%n.service" in unit


def test_the_recovery_unit_is_installed_and_runs_the_recovery_mode() -> None:
    import yaml

    from tests.test_node_notify_role import NOTIFY_ROLE

    unit = _render("kubelab-notify-recovered@.service.j2")
    assert "--recovered %i" in unit
    tasks = yaml.safe_load((NOTIFY_ROLE / "tasks/main.yml").read_text())
    [task] = [t for t in tasks if t.get("template", {}).get("src") == "kubelab-notify-recovered@.service.j2"]
    assert "node_notify_recovered_unit_name" in task["template"]["dest"]
