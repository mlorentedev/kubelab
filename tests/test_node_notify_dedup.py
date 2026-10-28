"""A unit that keeps failing pages once, reminds hourly, and says when it recovers (#2423).

Runs the SHIPPED `kubelab-notify.sh` end to end with `systemctl`, `journalctl` and `curl`
replaced by shims on PATH: the claim is about what reaches the operator's phone, so the
test counts the requests the script makes, never the text that describes them.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.test_node_notify_role import _defaults, _render

UNIT = "hermes-kubelab-vault-sync.service"
REMINDER = int(_defaults()["node_notify_reminder_seconds"])  # type: ignore[call-overload]
TTL = int(_defaults()["node_notify_state_ttl_seconds"])  # type: ignore[call-overload]


class Node:
    """A scratch directory standing in for one node: the rendered script, its state and its shims."""

    def __init__(self, root: Path, **render: object) -> None:
        self.root = root
        self.state = root / "state"
        self.sent = root / "sent.jsonl"
        self.result = root / "result"
        self.curl_exit = root / "curl-exit"
        self.systemctl = root / "systemctl.log"
        self.reset_exit = root / "reset-exit"
        self.environment = root / "environment"
        (root / "bin").mkdir()
        self.environment.mkdir()
        (root / "secret").write_text("tok")
        script = _render(
            "kubelab-notify.sh.j2",
            node_notify_secret_file=str(root / "secret"),
            node_notify_state_dir=str(self.state),
            **render,
        )
        self.script = root / "notify.sh"
        self.script.write_text(script)
        self.script.chmod(0o700)
        # `systemctl show -p <property> <unit>`: the unit's last result, or the
        # Environment= its unit file declares. Every call is logged, so a test
        # can see what the script asked systemd to do.
        self._shim(
            "systemctl",
            'printf "%s\\n" "$*" >> "$NODE_SYSTEMCTL"; case "$*" in'
            ' reset-failed*) exit "$(cat "$NODE_RESET_EXIT" 2>/dev/null || echo 0)" ;;'
            ' *Environment*) printf "Environment=%s\\n" "$(cat "$NODE_ENVIRONMENT/${@: -1}" 2>/dev/null)" ;;'
            ' *) printf "Result=%s\\n" "$(cat "$NODE_RESULT")" ;; esac',
        )
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

    def declare(self, environment: str, unit: str = UNIT) -> None:
        """What `Environment=` lines the unit's file carries, as systemd prints them."""
        (self.environment / unit).write_text(environment)

    def set_result(self, value: str) -> None:
        self.result.write_text(value)

    def _env(self) -> dict[str, str]:
        return {
            **os.environ,
            "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
            "NODE_RESULT": str(self.result),
            "NODE_SENT": str(self.sent),
            "NODE_CURL_EXIT": str(self.curl_exit),
            "NODE_SYSTEMCTL": str(self.systemctl),
            "NODE_RESET_EXIT": str(self.reset_exit),
            "NODE_ENVIRONMENT": str(self.environment),
        }

    def run(self, *args: str, unit: str = UNIT) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.script), *args, unit], capture_output=True, text=True, env=self._env(), timeout=60
        )

    def start(self, *args: str, unit: str = UNIT) -> subprocess.Popen[str]:
        """The script in the background, as systemd starts a second notice while the first is still out."""
        return subprocess.Popen(
            ["bash", str(self.script), *args, unit],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self._env(),
        )

    @contextmanager
    def locked(self, unit: str = UNIT) -> Iterator[None]:
        """Hold the unit's lock, as a notice of it does while its page is out."""
        self.state.mkdir(exist_ok=True)
        with open(self.state / f"{unit}.lock", "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def envelopes(self) -> list[dict[str, Any]]:
        if not self.sent.exists():
            return []
        return [json.loads(line) for line in self.sent.read_text().splitlines()]

    def titles(self) -> list[str]:
        return [envelope["title"] for envelope in self.envelopes()]

    def resets(self) -> list[str]:
        """The units the script asked systemd to clear the failed state of."""
        if not self.systemctl.exists():
            return []
        return [line.split()[-1] for line in self.systemctl.read_text().splitlines() if line.startswith("reset-failed")]

    def age_state(self, seconds: int, unit: str = UNIT) -> None:
        """Pretend the incident began `seconds` ago, and so did its last page, if one was delivered.

        A `last` of 0 means none was, and stays 0: aged, it would turn negative,
        which the script reads as a corrupt state and drops.
        """
        self.write_state(*self.read_state(unit), unit=unit, first_ago=seconds, last_ago=seconds)

    def read_state(self, unit: str = UNIT) -> tuple[int, int, int]:
        count, first, last = (self.state / unit).read_text().split()
        return int(count), int(first), int(last)

    def write_state(
        self, count: int, first: int, last: int, *, first_ago: int = 0, last_ago: int = 0, unit: str = UNIT
    ) -> None:
        self.state.mkdir(exist_ok=True)
        (self.state / unit).write_text(f"{count} {first - first_ago} {last - last_ago if last else 0}\n")


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


# The failure notifier for UNIT, read from the consumers' own `OnFailure=` line rather
# than rebuilt by the formula the script uses, so the two cannot agree by construction.
_ON_FAILURE = re.search(r"^OnFailure=(\S+)$", _render("kubelab-maintenance.service.j2"), re.MULTILINE)
assert _ON_FAILURE, "the maintenance unit no longer declares OnFailure="
NOTIFIER = _ON_FAILURE.group(1).replace("%n", UNIT)


def test_a_delivered_recovery_clears_the_failed_page_of_its_incident(node: Node) -> None:
    """#2733: a page n8n refused leaves its notifier failed, and nothing else ever runs it again.

    The next failure of the unit would restart the same instance and replace its
    result, but a recovered unit does not fail again, so the failed notifier
    outlived the incident it reported, on `systemctl --failed` and in Glances.
    """
    node.curl_exit.write_text("22")
    node.run()
    node.curl_exit.write_text("0")
    node.set_result("success")
    assert node.run("--recovered").returncode == 0
    assert "recovered" in node.titles()[-1], "the recovery of an incident whose page was refused was not sent"
    assert node.resets() == [NOTIFIER]


def test_the_next_failure_after_a_refused_first_page_is_still_the_first_page(node: Node) -> None:
    """`still failing (2 failures since the first page)` would name a page nobody received."""
    node.curl_exit.write_text("22")
    node.run()
    node.curl_exit.write_text("0")
    node.run()
    [title] = node.titles()[1:]
    assert "failed" in title and "still failing" not in title, title


def test_an_undelivered_recovery_leaves_the_failed_page_in_place(node: Node) -> None:
    """The operator has heard of neither the failure nor the recovery: the failed state is the only trace."""
    node.run()
    node.set_result("success")
    node.curl_exit.write_text("22")
    assert node.run("--recovered").returncode != 0
    assert node.resets() == []


def test_a_healthy_run_with_no_incident_resets_nothing(node: Node) -> None:
    node.set_result("success")
    node.run("--recovered")
    assert node.resets() == []


def test_a_reset_systemd_refuses_does_not_fail_a_delivered_recovery(node: Node) -> None:
    """The recovery reached the phone; failing here would leave a new failed unit for a closed incident."""
    node.run()
    node.set_result("success")
    node.reset_exit.write_text("1")
    assert node.run("--recovered").returncode == 0
    assert node.resets() == [NOTIFIER], "the reset was never attempted"
    assert not (node.state / UNIT).exists()


def test_an_undelivered_incident_ages_from_its_first_failure(node: Node) -> None:
    """#2733: measured from a `last` of 0, an incident whose only page was refused read as stale at once."""
    node.curl_exit.write_text("22")
    node.run()
    node.curl_exit.write_text("0")
    node.age_state(REMINDER + 5)
    node.set_result("success")
    assert node.run("--recovered").returncode == 0
    assert "recovered" in node.titles()[-1], "an incident within its TTL lost its recovery"
    assert node.resets() == [NOTIFIER]


def test_an_undelivered_incident_past_its_ttl_is_dropped(node: Node) -> None:
    """A unit whose runs are further apart than the TTL loses its recovery and the reset (#2757)."""
    node.curl_exit.write_text("22")
    node.run()
    node.curl_exit.write_text("0")
    node.age_state(TTL + 5)
    node.set_result("success")
    assert node.run("--recovered").returncode == 0
    assert len(node.titles()) == 1, "a recovery went out for an incident past its TTL"
    assert node.resets() == []


def test_a_unit_that_keeps_failing_past_the_ttl_still_closes_its_incident(node: Node) -> None:
    """The edge liveness check runs every minute, so with the uplink out its pages fail for hours.

    Each failure renews the state, and past the TTL one starts the incident over
    instead of dropping it, so the recovery that follows still finds it.
    """
    node.curl_exit.write_text("22")
    node.run()
    node.age_state(TTL + 5)
    node.run()
    node.curl_exit.write_text("0")
    node.set_result("success")
    assert node.run("--recovered").returncode == 0
    assert "recovered" in node.titles()[-1], node.titles()
    assert node.resets() == [NOTIFIER]


def test_a_long_incident_reminded_recently_is_not_stale(node: Node) -> None:
    """Its age runs from the last delivered page, not from the first failure."""
    node.run()
    node.write_state(*node.read_state(), first_ago=TTL + 5, last_ago=REMINDER + 5)
    node.run()
    assert "still failing" in node.titles()[-1], node.titles()


def test_a_recovery_waits_for_a_page_still_in_flight(node: Node) -> None:
    """#2733: a recovery that overtook the page would close the incident before the page landed.

    The failure notice records the count, then sends, then records the delivery,
    all under the unit's lock. The test holds that lock in its place.
    """
    node.write_state(1, int(time.time()), 0)
    node.set_result("success")
    with node.locked():
        recovery = node.start("--recovered")
        time.sleep(0.5)
        assert node.titles() == [], "the recovery did not wait for the page in flight"
        # The page lands, a second failure with it, and the notice records the delivery.
        node.write_state(2, node.read_state()[1], int(time.time()))
    assert recovery.wait(timeout=30) == 0, recovery.stderr.read() if recovery.stderr else ""
    [title] = node.titles()
    assert "recovered" in title and "2" in title, f"the recovery read the state before the lock: {title}"
    assert not (node.state / UNIT).exists()
    assert node.resets() == [NOTIFIER]


def test_a_recovery_that_waited_reads_the_result_the_unit_has_now(node: Node) -> None:
    """The unit failed again while the recovery waited: it must not close the new incident."""
    node.write_state(1, int(time.time()), 0)
    node.set_result("success")
    with node.locked():
        recovery = node.start("--recovered")
        time.sleep(0.5)
        node.set_result("exit-code")
        node.write_state(2, node.read_state()[1], int(time.time()))
    assert recovery.wait(timeout=30) == 0, recovery.stderr.read() if recovery.stderr else ""
    assert not any("recovered" in t for t in node.titles()), node.titles()
    assert (node.state / UNIT).exists(), "a recovery read before the lock closed an open incident"
    assert node.resets() == []


def test_a_notice_whose_lock_is_held_past_the_wait_still_goes_out(tmp_path: Path) -> None:
    """A late page beats a lost one, and failing here would leave a failed notifier of its own."""
    node = Node(tmp_path, node_notify_lock_wait_seconds=1)
    with node.locked():
        result = node.run()
    assert result.returncode == 0, result.stderr
    assert "failed" in node.titles()[0]
    assert "without the lock" in result.stderr


def test_a_hand_run_of_the_recovery_mode_while_the_unit_fails_closes_nothing(node: Node) -> None:
    node.run()
    node.run()
    assert node.run("--recovered").returncode == 0
    assert len(node.titles()) == 1, "a false recovery page"
    assert (node.state / UNIT).exists(), "the open incident was discarded"


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


@pytest.mark.parametrize("template", ["vault-sync.service.j2", "vault-mirror.service.j2", "docs-mirror.service.j2"])
def test_the_frequent_agent_stack_units_close_their_incidents(template: str) -> None:
    """Timers that fire every few minutes would otherwise silence a flap for the whole reminder window."""
    from tests.test_agent_stack_role import _environment, _resolved

    env = _environment()
    unit = env.get_template(template).render(**_resolved(env))
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


PAGE = "KUBELAB_NOTIFY_SEVERITY=page"


@pytest.fixture(
    params=[
        pytest.param(PAGE, id="alone"),
        pytest.param(f"LANG=C.UTF-8 {PAGE} STATE=/var/lib/x", id="among-others"),
    ]
)
def paged(node: Node, request: pytest.FixtureRequest) -> Node:
    """A unit that declares `page`, as systemd prints it: `Environment=` then the variables, space-separated."""
    node.declare(request.param)
    return node


def test_a_unit_that_declares_page_pages_and_every_other_unit_keeps_the_default(paged: Node) -> None:
    """#2684: the edge's own units need a person now, the rest of the fleet does not."""
    paged.run()
    paged.run(unit="node-backup-ship.service")
    assert [e["severity"] for e in paged.envelopes()] == ["page", "log"]


def test_a_paged_unit_keeps_its_severity_on_the_reminder(paged: Node) -> None:
    paged.run()
    paged.age_state(REMINDER + 5)
    paged.run()
    assert [e["severity"] for e in paged.envelopes()] == ["page", "page"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed: the router was NOT run")
def test_the_recovery_of_a_paged_unit_closes_the_alarm_instead_of_raising_another(paged: Node) -> None:
    """The router sends a `page` envelope as a failure unless it is marked resolved."""
    from tests.test_n8n_notify_router import _route

    paged.run()
    paged.set_result("success")
    paged.run("--recovered")
    page, recovery = (_route(envelope) for envelope in paged.envelopes())
    assert (page["tag"], page["type"]) == ("page", "failure")
    assert (recovery["tag"], recovery["type"]) == ("page", "info"), recovery["title"]


def test_exercising_the_path_for_a_healthy_paged_unit_is_not_an_alarm(paged: Node) -> None:
    """`make maintain-notify-test` starts the notifier by hand for a unit that did not fail."""
    paged.set_result("success")
    paged.run()
    assert [e["severity"] for e in paged.envelopes()] == ["log"]


@pytest.mark.parametrize(
    "declared",
    [
        pytest.param("KUBELAB_NOTIFY_SEVERITY=critical", id="a-level-the-router-does-not-route"),
        pytest.param("KUBELAB_NOTIFY_SEVERITY=", id="empty"),
        pytest.param("XKUBELAB_NOTIFY_SEVERITY=page", id="another-variable"),
        pytest.param("", id="nothing"),
    ],
)
def test_anything_but_a_declared_page_keeps_the_default(node: Node, declared: str) -> None:
    node.declare(declared)
    node.run()
    assert [e["severity"] for e in node.envelopes()] == ["log"]
