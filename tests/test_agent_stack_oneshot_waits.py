"""A oneshot the play starts is waited for before the play reads what it left (#3575).

`ansible.builtin.systemd: state: started` blocks on a oneshot only when it issues the start
itself. When the unit is already `activating` (its timer fired, or another caller started
it) the module counts it as running, issues no `systemctl start` and returns at once, so the
`stat` that followed read a half-finished run: ace2, 2026-11-16, the curator's analyzer
(~64 s) was still running when `candidates.json` was checked. `systemctl start --wait` has
the same hole, for the same reason: it waits for the job it queued, and a unit already
activating queues none.

So the run is `start --wait`, then a poll of `ActiveState` until the unit has settled,
then `Result=success` read from systemd, and only then the file. These tests read the YAML
for the shape and run the real tasks against a stand-in `systemctl` for the effect.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.shells import child_env

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
CURATOR = ROLE / "tasks/curator.yml"

UNIT = "hermes-kubelab-curator-analyze"
RELOAD = "Reload systemd for the analyzer units"
BEFORE = "Note when the candidates were last written"
START = "Run the analyzer once"
WAIT = "Wait for the analyzer run to settle"
RESULT = "Read how the analyzer run ended"
RESULT_OK = "Verify the analyzer run succeeded"
AFTER = "Look at the candidates again"
MTIME_OK = "Verify this run wrote the candidates"

# The analyzer takes about 64 s on ace2; the poll must outlast it with room to spare.
RUN_SECONDS = 64
SETTLED_STATES = {"inactive", "failed"}

# The guard reads the `agent_stack` role only. `playbooks/backup-node.yml` and
# `playbooks/maintenance-notify-test.yml` also start a oneshot with `state: started` and read
# its result, but both `state: stopped` the unit first, so nothing can have it activating when
# the start is issued (bar the ms between the two tasks) and `started` does block there.
#
# Run-once tasks of the same shape that still start their oneshot without waiting for it
# (#3630). A set that only shrinks: `test_the_known_gaps_are_still_gaps` fails for an entry
# whose task has since been fixed, so the exemption cannot outlive the defect.
KNOWN_UNWAITED = {
    "agent_stack_vault_sync_unit",
    "agent_stack_vault_mirror_unit",
    "agent_stack_docs_mirror_unit",
}


def _load(path: Path) -> list[dict]:
    """The tasks of a file in play order, a block's children right after the block."""
    flat: list[dict] = []
    for task in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _curator() -> list[dict]:
    return _load(CURATOR)


def _by_name(name: str) -> dict:
    (task,) = [t for t in _curator() if t.get("name") == name]
    return task


def _index(name: str) -> int:
    (i,) = [i for i, t in enumerate(_curator()) if t.get("name") == name]
    return i


def _command_argv(task: dict) -> list[str]:
    body = task.get("ansible.builtin.command") or task.get("command") or {}
    return list(body.get("argv", [])) if isinstance(body, dict) else str(body).split()


def _systemd_started(task: dict) -> str | None:
    """The unit a task starts through the systemd module, or None."""
    spec = task.get("ansible.builtin.systemd") or task.get("systemd") or {}
    return spec.get("name") if spec.get("state") == "started" else None


def _oneshot_unit_vars() -> set[str]:
    """Unit variables whose `.service` is a oneshot that ends when its run ends.

    Derived from the role itself: the template task that installs `{{ VAR }}.service`
    names its source, and the source says `Type=oneshot` without `RemainAfterExit=yes`.
    A oneshot that stays `active` after running is a switch, not a run: `started` is the
    whole of what it needs.
    """
    found: set[str] = set()
    for path in sorted((ROLE / "tasks").glob("*.yml")):
        for task in _load(path):
            spec = task.get("ansible.builtin.template") or {}
            dest = re.fullmatch(r"/etc/systemd/system/\{\{ (\w+) \}\}\.\{\{ item \}\}", spec.get("dest", ""))
            src = re.fullmatch(r"([\w-]+)\.\{\{ item \}\}\.j2", spec.get("src", ""))
            if not (dest and src):
                continue
            text = (ROLE / "templates" / f"{src.group(1)}.service.j2").read_text(encoding="utf-8")
            if re.search(r"^Type=oneshot", text, re.M) and not re.search(r"^RemainAfterExit=yes", text, re.M):
                found.add(dest.group(1))
    return found


def _is_poll(task: dict, unit_var: str) -> bool:
    """A task that re-reads this unit's ActiveState until it changes.

    It must name the unit it waits for: a poll of another unit in the same file excuses nothing.
    """
    argv = _command_argv(task)
    return "until" in task and "ActiveState" in argv and argv[-1:] == [f"{{{{ {unit_var} }}}}.service"]


def _unwaited(tasks: list[dict], oneshots: set[str]) -> list[str]:
    """Unit variables a file starts with `state: started` and never polls afterwards."""
    gaps: list[str] = []
    for i, task in enumerate(tasks):
        name = _systemd_started(task) or ""
        match = re.fullmatch(r"\{\{ (\w+) \}\}\.service", name)
        if match and match.group(1) in oneshots and not any(_is_poll(t, match.group(1)) for t in tasks[i + 1 :]):
            gaps.append(match.group(1))
    return gaps


def _role_gaps() -> set[str]:
    oneshots = _oneshot_unit_vars()
    gaps: set[str] = set()
    for path in sorted((ROLE / "tasks").glob("*.yml")):
        gaps.update(_unwaited(_load(path), oneshots))
    return gaps


# --- the guard: no oneshot is started and left unwaited -----------------------


def test_the_oneshots_are_found_from_the_role_not_listed_by_hand() -> None:
    oneshots = _oneshot_unit_vars()
    assert "agent_stack_curator_unit" in oneshots
    assert KNOWN_UNWAITED <= oneshots
    # RemainAfterExit=yes: `active` is the finished state of a switch, not a run in flight.
    assert "agent_stack_egress_unit" not in oneshots


def test_no_oneshot_is_started_with_state_started_and_left_unwaited() -> None:
    assert _role_gaps() - KNOWN_UNWAITED == set(), (
        "a oneshot started with `state: started` returns before it finishes (and not at all when "
        "its timer already started it): run it with `systemctl start --wait`, poll ActiveState "
        "until it settles, then read Result (#3575)"
    )


def test_the_known_gaps_are_still_gaps() -> None:
    assert KNOWN_UNWAITED - _role_gaps() == set(), "fixed since #3630: drop it from KNOWN_UNWAITED"


def test_the_guard_sees_a_started_oneshot_with_nothing_after_it() -> None:
    tasks = yaml.safe_load(
        """
        - name: Run it
          ansible.builtin.systemd: {name: "{{ a_unit }}.service", state: started}
        - name: Look at what it left
          ansible.builtin.stat: {path: /x}
        """
    )
    assert _unwaited(tasks, {"a_unit"}) == ["a_unit"]
    assert _unwaited(tasks, set()) == [], "a unit that is not a oneshot needs no wait"


def test_the_guard_accepts_a_poll_and_ignores_one_that_comes_before() -> None:
    def poll(unit: str) -> dict:
        argv = ["systemctl", "show", "-p", "ActiveState", "--value", f"{{{{ {unit} }}}}.service"]
        return {"name": "Wait", "ansible.builtin.command": {"argv": argv}}

    start = {"name": "Run", "ansible.builtin.systemd": {"name": "{{ a_unit }}.service", "state": "started"}}
    assert _unwaited([start, {**poll("a_unit"), "until": "x"}], {"a_unit"}) == []
    assert _unwaited([{**poll("a_unit"), "until": "x"}, start], {"a_unit"}) == ["a_unit"], (
        "a poll before waits for nothing"
    )
    assert _unwaited([start, poll("a_unit")], {"a_unit"}) == ["a_unit"], "without `until` it reads the state once"


def test_a_poll_of_another_unit_does_not_excuse_this_one() -> None:
    def started(unit: str) -> dict:
        return {"name": "Run", "ansible.builtin.systemd": {"name": f"{{{{ {unit} }}}}.service", "state": "started"}}

    other = {
        "name": "Wait",
        "until": "x",
        "ansible.builtin.command": {"argv": ["systemctl", "show", "-p", "ActiveState", "{{ b_unit }}.service"]},
    }
    assert _unwaited([started("a_unit"), started("b_unit"), other], {"a_unit", "b_unit"}) == ["a_unit"]


# --- the curator's analyzer: the shape of the wait -----------------------------


def test_the_run_goes_through_systemctl_start_wait() -> None:
    argv = _command_argv(_by_name(START))
    assert argv[:3] == ["systemctl", "start", "--wait"], argv
    assert argv[-1] == "{{ agent_stack_curator_unit }}.service"
    assert _systemd_started(_by_name(START)) is None


def test_the_run_polls_until_the_unit_is_no_longer_running() -> None:
    task = _by_name(WAIT)
    argv = _command_argv(task)
    assert argv[:2] == ["systemctl", "show"] and "ActiveState" in argv and "--value" in argv, argv
    assert argv[-1] == "{{ agent_stack_curator_unit }}.service"
    assert task["register"]
    condition = task["until"]
    assert task["register"] in condition and "stdout" in condition, "polls the output it registered"
    for running in ("activating", "active", "deactivating", "reloading"):
        assert running in condition, f"{running!r} is a run in flight, not a settled unit"
    for settled in SETTLED_STATES:
        assert settled not in condition.split("not in")[-1], f"{settled!r} is a settled state"


def test_the_poll_outlasts_the_run_with_room_to_spare() -> None:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    task = _by_name(WAIT)
    retries = str(task["retries"])
    delay = str(task["delay"])
    for var in (retries, delay):
        assert re.fullmatch(r"\{\{ (agent_stack_curator_wait_\w+) \}\}", var), "sized in defaults, not buried"
    seconds = int(defaults[re.search(r"\{\{ (\w+) \}\}", retries).group(1)]) * int(
        defaults[re.search(r"\{\{ (\w+) \}\}", delay).group(1)]
    )
    assert seconds >= 2 * RUN_SECONDS, f"{seconds}s of polling for a {RUN_SECONDS}s run"
    # The unit's own TimeoutStartSec bounds a run; waiting past it would hide a hung unit.
    assert seconds <= 600, f"{seconds}s outlasts the unit's TimeoutStartSec=10min"


def test_the_result_systemd_recorded_must_be_success() -> None:
    read = _by_name(RESULT)
    argv = _command_argv(read)
    assert argv[:2] == ["systemctl", "show"] and "Result" in argv and "--value" in argv, argv
    check = _by_name(RESULT_OK)
    assert read["register"] in " ".join(check["ansible.builtin.assert"]["that"])
    assert "success" in " ".join(check["ansible.builtin.assert"]["that"])
    assert read["register"] in check["ansible.builtin.assert"]["fail_msg"], "the message names what systemd recorded"


def test_each_step_runs_in_the_order_that_makes_the_next_one_true() -> None:
    order = [_index(n) for n in (START, WAIT, RESULT, RESULT_OK, AFTER, MTIME_OK)]
    assert order == sorted(order), order
    assert _index(RELOAD) < _index(START), "the run reads the unit files the play just wrote"
    assert _index(BEFORE) < _index(START), "the mtime to beat is taken before the run"


def test_the_reload_still_precedes_the_run() -> None:
    task = _by_name(RELOAD)
    spec = task.get("ansible.builtin.systemd") or task.get("ansible.builtin.systemd_service")
    assert spec["daemon_reload"] is True


@pytest.mark.parametrize("name", [RELOAD, START, WAIT, RESULT])
def test_a_measurement_reports_no_change(name: str) -> None:
    """The run is the measurement: the units are the change. Reporting it would end `changed=0`."""
    assert _by_name(name)["changed_when"] is False


@pytest.mark.parametrize("name", [WAIT, RESULT])
def test_a_read_runs_in_a_dry_run(name: str) -> None:
    """The repo's rule for a read (ANSIBLE-059): it has no side effect, so `--check` runs it."""
    assert _by_name(name)["check_mode"] is False


def test_the_wait_lets_a_dry_run_through_and_the_verdicts_wait_for_a_real_run() -> None:
    """`--check` starts nothing, so on a node whose unit is busy or new it must not wait out the retries."""
    wait = _by_name(WAIT)
    assert "ansible_check_mode" in wait["until"] and "ansible_check_mode" in wait["ignore_errors"]
    for name in (RESULT_OK, MTIME_OK):
        assert _by_name(name)["when"] == "not ansible_check_mode", f"{name!r} judges a run a dry run never made"


# --- the effect: the real tasks against a stand-in systemctl -------------------
# The tests above read the YAML. What decides whether the play races is what the tasks do
# against a unit that is already activating, so run them against one.

STUB = """#!{python}
import json, os, pathlib, sys, time

home = pathlib.Path(os.environ["STUB_HOME"])
cfg = json.loads((home / "config.json").read_text())
args = sys.argv[1:]
with (home / "calls.log").open("a") as log:
    log.write(" ".join(args) + "\\n")
polls = home / "polls"


def run_unit(result):
    out = pathlib.Path(cfg["out"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidates.json").write_text(json.dumps({{"corpus_files": 3, "units": 1}}))
    (home / "result").write_text(result)


if args[:2] == ["start", "--wait"]:
    # An unit already activating queues no job: --wait returns at once.
    if cfg["scenario"] in ("inflight", "inflight_failed", "stuck"):
        sys.exit(0)
    run_unit("success")
    sys.exit(0)

if args[:1] == ["show"] and "ActiveState" in args:
    n = int(polls.read_text()) + 1 if polls.exists() else 1
    polls.write_text(str(n))
    if cfg["scenario"] == "stuck" or n <= cfg.get("running_polls", 0):
        print("activating")
    else:
        if cfg["scenario"] in ("inflight", "inflight_failed") and not (home / "result").exists():
            run_unit("success" if cfg["scenario"] == "inflight" else "exit-code")
        print("inactive")
    sys.exit(0)

if args[:1] == ["show"] and "Result" in args:
    print((home / "result").read_text() if (home / "result").exists() else "success")
    sys.exit(0)

sys.exit(0)
"""

needs_ansible = pytest.mark.skipif(
    shutil.which("ansible-playbook") is None or sys.platform == "win32",
    reason="ansible-playbook not on PATH (no Windows controller): the wait was NOT executed",
)


def _stand_in(tmp_path: Path, scenario: str, running_polls: int = 0) -> dict[str, str]:
    home = tmp_path / "stub"
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True)
    out = tmp_path / "vault/curator"
    out.mkdir(parents=True)
    old = out / "candidates.json"
    old.write_text(json.dumps({"corpus_files": 1, "units": 1}), encoding="utf-8", newline="\n")
    os.utime(old, (old.stat().st_atime - 3600, old.stat().st_mtime - 3600))
    (home / "config.json").write_text(
        json.dumps({"scenario": scenario, "running_polls": running_polls, "out": str(out)}),
        encoding="utf-8",
        newline="\n",
    )
    script = bin_dir / "systemctl"
    script.write_text(STUB.format(python=sys.executable), encoding="utf-8", newline="\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return child_env({"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "STUB_HOME": str(home)})


def _run(
    tmp_path: Path, env: dict[str, str], retries: int = 6, check: bool = False
) -> subprocess.CompletedProcess[str]:
    names = (BEFORE, START, WAIT, RESULT, RESULT_OK, AFTER, MTIME_OK)
    by_name = {t.get("name"): t for t in _curator()}
    play = [
        {
            "hosts": "localhost",
            "gather_facts": False,
            "connection": "local",
            "vars": {
                "agent_stack_curator_unit": UNIT,
                "agent_stack_curator_out": str(tmp_path / "vault/curator"),
                "agent_stack_curator_wait_retries": retries,
                "agent_stack_curator_wait_delay": 0,
            },
            "tasks": [by_name[n] for n in names],
        }
    ]
    playbook = tmp_path / "curator.yml"
    playbook.write_text(yaml.safe_dump(play), encoding="utf-8", newline="\n")
    full = {
        **os.environ,
        **env,
        "ANSIBLE_LOCALHOST_WARNING": "False",
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_FORCE_COLOR": "0",
    }
    return subprocess.run(
        ["ansible-playbook", str(playbook), "-i", "localhost,", *(["--check"] if check else [])],
        cwd=tmp_path,
        env=full,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _changed(result: subprocess.CompletedProcess[str]) -> int:
    (line,) = [ln for ln in result.stdout.splitlines() if ln.startswith("localhost") and "changed=" in ln]
    return int(line.split("changed=")[1].split()[0])


def _polls(env: dict[str, str]) -> int:
    path = Path(env["STUB_HOME"]) / "polls"
    return int(path.read_text(encoding="utf-8")) if path.exists() else 0


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a stand-in systemctl")
def test_an_idle_unit_runs_and_the_provision_reports_no_change(tmp_path: Path) -> None:
    env = _stand_in(tmp_path, "idle")

    first = _run(tmp_path, env)
    second = _run(tmp_path, env)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    assert _changed(first) == 0 and _changed(second) == 0, "the run is a measurement, not a change"
    assert "start --wait " + UNIT + ".service" in (Path(env["STUB_HOME"]) / "calls.log").read_text(encoding="utf-8")


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a stand-in systemctl")
def test_a_unit_its_timer_already_started_is_waited_for(tmp_path: Path) -> None:
    """ace2, 2026-11-16: `--wait` returned at once, the file was still last week's."""
    env = _stand_in(tmp_path, "inflight", running_polls=3)

    result = _run(tmp_path, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _polls(env) == 4, "three polls saw the unit activating, the fourth saw it settle"
    assert _changed(result) == 0


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a stand-in systemctl")
def test_a_run_that_ended_in_failure_fails_the_provision_with_what_systemd_recorded(tmp_path: Path) -> None:
    """A fresh `candidates.json` does not make a failed run a good one."""
    env = _stand_in(tmp_path, "inflight_failed", running_polls=1)

    result = _run(tmp_path, env)

    assert result.returncode != 0
    assert "exit-code" in result.stdout, result.stdout


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a stand-in systemctl")
def test_a_unit_that_never_settles_fails_instead_of_passing_on_a_stale_file(tmp_path: Path) -> None:
    env = _stand_in(tmp_path, "stuck")

    result = _run(tmp_path, env, retries=3)

    assert result.returncode != 0
    assert _polls(env) == 4, "one attempt plus three retries, then it gives up"
    assert (
        Path(tmp_path / "vault/curator/candidates.json").read_text(encoding="utf-8")
        == '{"corpus_files": 1, "units": 1}'
    )


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a stand-in systemctl")
def test_a_dry_run_makes_one_attempt_instead_of_waiting_out_a_busy_unit(tmp_path: Path) -> None:
    env = _stand_in(tmp_path, "stuck")

    result = _run(tmp_path, env, retries=3, check=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _polls(env) == 1
    assert "start --wait" not in (Path(env["STUB_HOME"]) / "calls.log").read_text(encoding="utf-8")
