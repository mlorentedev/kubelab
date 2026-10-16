"""hermes-kubelab's scheduled jobs (spec AI-012 AC4 and AC5).

The jobs are declared in `common.yaml` and reconciled against the gateway's
`cron/jobs.json` by name. The diff is a pure function in
`files/hermes-jobs.py`, so these tests run it against jobs.json records in the
shapes Hermes v0.22.1 stores (measured 2026-10-15), not against a mock of the
CLI. What they cannot prove, that `hermes cron create|edit|remove` accept the
arguments and that the second provision reports `changed=0`, is the live row of
`verification.md`.
"""

from __future__ import annotations

import copy
import re
import types
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
COMMON = REPO / "infra/config/values/common.yaml"
PREFIX = "kubelab:"
HOME_CHANNEL = "C0TESTHOME"


def _planner() -> types.ModuleType:
    """Compiled from source, never imported: an import writes a .pyc into the role's
    files/, which other tests read as text."""
    path = ROLE / "files/hermes-jobs.py"
    module = types.ModuleType("hermes_jobs")
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


def _hermes() -> dict:
    return yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]


def _declaration(**jobs: dict) -> dict:
    """What the role hands the planner: the prefix, the delivery default and the jobs."""
    return {"name_prefix": PREFIX, "default_deliver": f"slack:{HOME_CHANNEL}", "jobs": jobs}


AGENT_JOB = {"mode": "agent", "schedule": "0 22 * * *", "prompt": "Write the day's record."}
SCRIPT_JOB = {"mode": "script", "schedule": "5 8 * * *", "script": "digest.py"}


def _stored(name: str, **over: object) -> dict:
    """A jobs.json record in the form Hermes v0.22.1 writes for an agent job
    created with `--deliver slack:<home> --failure-deliver slack:<home>`."""
    record = {
        "id": "0123456789ab",
        "name": name,
        "prompt": "Write the day's record.",
        "skills": [],
        "model": None,
        "provider": None,
        "script": None,
        "no_agent": False,
        "schedule": {"kind": "cron", "expr": "0 22 * * *", "display": "0 22 * * *"},
        "deliver": f"slack:{HOME_CHANNEL}",
        "failure_deliver": f"slack:{HOME_CHANNEL}",
        "enabled": True,
        "state": "scheduled",
        "workdir": None,
    }
    return {**record, **over}


def _plan(declared: dict, state: list[dict]) -> list[dict]:
    return _planner().plan(copy.deepcopy(declared), copy.deepcopy(state))


# --------------------------------------------------------------------------- create


def test_a_declared_job_the_gateway_lacks_is_created_under_the_role_prefix() -> None:
    [action] = _plan(_declaration(record=AGENT_JOB), [])
    assert action["op"] == "create"
    assert action["name"] == f"{PREFIX}record"
    argv = action["argv"]
    assert argv[:2] == ["cron", "create"]
    assert argv[argv.index("--name") + 1] == f"{PREFIX}record"
    assert argv[-2:] == ["0 22 * * *", "Write the day's record."]


def test_every_job_delivers_to_the_home_channel_and_reports_failure_there_too() -> None:
    [action] = _plan(_declaration(record=AGENT_JOB), [])
    argv = action["argv"]
    assert argv[argv.index("--deliver") + 1] == f"slack:{HOME_CHANNEL}"
    assert argv[argv.index("--failure-deliver") + 1] == f"slack:{HOME_CHANNEL}"


def test_an_agent_job_may_carry_a_script_that_feeds_its_prompt() -> None:
    """The script's stdout is injected into the turn (and can stop it: the wake gate)."""
    job = {**AGENT_JOB, "script": "activity.py"}
    [action] = _plan(_declaration(record=job), [])
    argv = action["argv"]
    assert argv[argv.index("--script") + 1] == "activity.py"
    assert "--no-agent" not in argv, "the agent still runs; the script only gives it data"
    stored = _stored(f"{PREFIX}record", script="activity.py")
    assert _plan(_declaration(record=job), [stored]) == []


def test_a_script_job_runs_the_script_and_no_model() -> None:
    [action] = _plan(_declaration(digest=SCRIPT_JOB), [])
    argv = action["argv"]
    assert "--no-agent" in argv
    assert argv[argv.index("--script") + 1] == "digest.py"
    assert "--model" not in argv


def test_a_job_follows_cron_model_unless_it_declares_one() -> None:
    [plain] = _plan(_declaration(record=AGENT_JOB), [])
    assert "--model" not in plain["argv"]
    [pinned] = _plan(_declaration(record={**AGENT_JOB, "model": "m1", "provider": "custom"}), [])
    argv = pinned["argv"]
    assert argv[argv.index("--model") + 1] == "m1"
    assert argv[argv.index("--provider") + 1] == "custom"


def test_a_model_without_its_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="provider"):
        _plan(_declaration(record={**AGENT_JOB, "model": "m1"}), [])


@pytest.mark.parametrize(
    ("job", "reason"),
    [
        ({"mode": "agent", "schedule": "0 22 * * *"}, "prompt"),
        ({"mode": "script", "schedule": "0 22 * * *"}, "script"),
        ({"mode": "agent", "schedule": "tomorrow", "prompt": "x"}, "schedule"),
        ({"mode": "both", "schedule": "0 22 * * *", "prompt": "x"}, "mode"),
        ({"mode": "script", "schedule": "0 22 * * *", "script": "../x.py"}, "script"),
    ],
    ids=["no-prompt", "no-script", "bad-schedule", "bad-mode", "script-path"],
)
def test_a_malformed_declaration_fails_the_plan_before_anything_is_changed(job: dict, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        _plan(_declaration(record=job), [])


# --------------------------------------------------------------------------- idempotence


def test_a_gateway_that_already_matches_plans_nothing() -> None:
    state = [_stored(f"{PREFIX}record")]
    assert _plan(_declaration(record=AGENT_JOB), state) == []


def test_an_interval_schedule_matches_the_minutes_hermes_stores() -> None:
    job = {**AGENT_JOB, "schedule": "every 2h"}
    stored = _stored(f"{PREFIX}record", schedule={"kind": "interval", "minutes": 120, "display": "every 120m"})
    assert _plan(_declaration(record=job), [stored]) == []


def test_a_script_job_matches_its_stored_form() -> None:
    stored = _stored(
        f"{PREFIX}digest",
        prompt="",
        script="digest.py",
        no_agent=True,
        schedule={"kind": "cron", "expr": "5 8 * * *", "display": "5 8 * * *"},
    )
    assert _plan(_declaration(digest=SCRIPT_JOB), [stored]) == []


# --------------------------------------------------------------------------- edit


@pytest.mark.parametrize(
    "drift",
    [
        {"prompt": "something else"},
        {"schedule": {"kind": "cron", "expr": "0 21 * * *", "display": "0 21 * * *"}},
        {"deliver": "slack:C0OTHER"},
        {"failure_deliver": None},
        {"skills": ["extra"]},
        {"model": "m1", "provider": "custom"},
        {"script": "x.py", "no_agent": True},
    ],
    ids=["prompt", "schedule", "deliver", "failure-deliver", "skills", "model", "mode"],
)
def test_a_changed_field_edits_the_job_it_belongs_to(drift: dict) -> None:
    state = [_stored(f"{PREFIX}record", **drift)]
    [action] = _plan(_declaration(record=AGENT_JOB), state)
    assert action["op"] == "edit"
    assert action["id"] == "0123456789ab"
    assert action["argv"][:3] == ["cron", "edit", "0123456789ab"]


def test_an_edit_states_every_managed_field_so_a_cleared_one_is_cleared() -> None:
    """`hermes cron edit` leaves what it is not told about, so a field dropped from
    the declaration has to be named, with its empty value."""
    state = [_stored(f"{PREFIX}record", model="m1", provider="custom", skills=["extra"], prompt="old")]
    [action] = _plan(_declaration(record=AGENT_JOB), state)
    argv = action["argv"]
    assert argv[argv.index("--model") + 1] == ""
    assert argv[argv.index("--provider") + 1] == ""
    assert "--clear-skills" in argv
    assert argv[argv.index("--prompt") + 1] == "Write the day's record."


def test_a_paused_job_the_role_declared_is_resumed() -> None:
    state = [_stored(f"{PREFIX}record", enabled=False, state="paused")]
    [action] = _plan(_declaration(record=AGENT_JOB), state)
    assert action["op"] == "resume"
    assert action["argv"] == ["cron", "resume", "0123456789ab"]


# --------------------------------------------------------------------------- remove


def test_a_dropped_declaration_removes_the_job_the_role_created() -> None:
    state = [_stored(f"{PREFIX}gone", id="aaaaaaaaaaaa")]
    [action] = _plan(_declaration(), state)
    assert action == {
        "op": "remove",
        "name": f"{PREFIX}gone",
        "id": "aaaaaaaaaaaa",
        "argv": ["cron", "remove", "aaaaaaaaaaaa"],
    }


def test_a_job_the_role_did_not_create_is_never_touched() -> None:
    """Its name has no prefix, so it is the agent's or the operator's, whatever it does."""
    foreign = [
        _stored("weekly research", id="bbbbbbbbbbbb"),
        _stored("record", id="cccccccccccc"),
        _stored("Kubelab:record", id="dddddddddddd"),
    ]
    assert _plan(_declaration(), foreign) == []
    [action] = _plan(_declaration(record=AGENT_JOB), foreign)
    assert action["op"] == "create", "a foreign job named like a declared one is not adopted"


def test_two_owned_jobs_with_one_name_fail_the_plan_instead_of_picking_one() -> None:
    """Hermes names are not unique (the id is), so there is no safe choice."""
    state = [_stored(f"{PREFIX}record", id="aaaaaaaaaaaa"), _stored(f"{PREFIX}record", id="bbbbbbbbbbbb")]
    with pytest.raises(ValueError, match="more than one"):
        _plan(_declaration(record=AGENT_JOB), state)


def test_the_plan_is_ordered_so_a_second_run_of_the_same_inputs_is_identical() -> None:
    declared = _declaration(b=AGENT_JOB, a=AGENT_JOB)
    state = [_stored(f"{PREFIX}z", id="aaaaaaaaaaaa"), _stored(f"{PREFIX}y", id="bbbbbbbbbbbb")]
    first = _plan(declared, state)
    assert first == _plan(declared, list(reversed(state)))
    assert [a["op"] for a in first] == ["remove", "remove", "create", "create"], "removals first, then creations"


# --------------------------------------------------------------------------- the real declaration


def test_the_declared_jobs_are_valid_and_all_new_on_an_empty_gateway() -> None:
    cron = _hermes()["cron"]
    declared = {
        "name_prefix": cron["name_prefix"],
        "default_deliver": f"slack:{_hermes()['slack']['home_channel']['id']}",
        "jobs": cron["jobs"],
    }
    actions = _plan(declared, [])
    assert {a["name"] for a in actions} == {f"{cron['name_prefix']}{key}" for key in cron["jobs"]}
    assert {a["op"] for a in actions} == {"create"}
    assert cron["name_prefix"] == PREFIX


# --------------------------------------------------------------------------- the role's wiring


def _job_tasks() -> list[dict]:
    path = ROLE / "tasks/hermes_jobs.yml"
    assert path.exists(), "the reconcile tasks live in tasks/hermes_jobs.yml"
    return yaml.safe_load(path.read_text())


def _flat(tasks: list[dict]) -> list[dict]:
    out: list[dict] = []
    for task in tasks:
        out.append(task)
        for key in ("block", "rescue", "always"):
            out.extend(_flat(task.get(key, [])))
    return out


def test_the_reconcile_is_part_of_the_gateway_deploy() -> None:
    text = (ROLE / "tasks/hermes.yml").read_text()
    assert "hermes_jobs.yml" in text


def test_the_plan_is_read_only_and_runs_in_a_dry_run_too() -> None:
    [plan] = [t for t in _flat(_job_tasks()) if "plan" in t.get("name", "").lower() and "command" in str(t)]
    assert plan.get("check_mode") is False, "a dry run must still compute the diff"
    assert plan.get("changed_when") is False


def test_the_diff_decides_changed_and_a_dry_run_changes_nothing() -> None:
    tasks = _flat(_job_tasks())
    [report] = [t for t in tasks if "ansible.builtin.debug" in t and "changed_when" in t]
    assert "_agent_stack_hermes_jobs_plan" in str(report["changed_when"])
    applying = [t for t in tasks if "loop" in t and "ansible.builtin.command" in t]
    assert applying, "the plan's actions are applied by a loop"
    for task in applying:
        assert "ansible_check_mode" in str(task.get("when", "")), f"{task['name']!r} would run in a dry run"


def test_jobs_are_written_as_the_gateways_user_through_the_cli_and_never_restart_it() -> None:
    """R6 (verification.md): the running gateway reads jobs.json on every tick."""
    text = (ROLE / "tasks/hermes_jobs.yml").read_text()
    commands = [t for t in _flat(_job_tasks()) if "ansible.builtin.command" in t]
    assert len(commands) == 2
    for task in commands:
        argv = re.sub(r"[\[\]'\",]", " ", str(task["ansible.builtin.command"]["argv"]))
        assert "docker exec" in " ".join(argv.split()), task["name"]
        assert "-u hermes" in " ".join(argv.split()), (
            f"{task['name']!r}: a root-written job file is unreadable to the gateway"
        )
    for forbidden in ("force-recreate", "restart", "docker compose", "up -d"):
        assert forbidden not in text, f"{forbidden!r}: R6 says the gateway picks the jobs up as they are"


def test_the_planner_arrives_on_stdin_so_it_never_lands_where_the_agent_writes() -> None:
    task = next(t for t in _flat(_job_tasks()) if "plan" in t.get("name", "").lower() and "command" in str(t))
    assert "hermes-jobs.py" in str(task.get("args", "")) + str(task)
    assert "stdin" in str(task)


def test_an_edit_switches_the_job_between_agent_and_script_mode() -> None:
    """A job that stopped being a script job must run its agent again, and the
    reverse: `edit` keeps the old mode unless it is told the new one."""
    was_script = [_stored(f"{PREFIX}record", script="activity.py", no_agent=True, prompt="")]
    [action] = _plan(_declaration(record=AGENT_JOB), was_script)
    assert "--agent" in action["argv"]
    assert "--no-agent" not in action["argv"]

    was_agent = [_stored(f"{PREFIX}digest")]
    [action] = _plan(_declaration(digest=SCRIPT_JOB), was_agent)
    assert "--no-agent" in action["argv"]
    assert "--agent" not in action["argv"]


def test_the_planners_refusal_fails_the_play_even_in_a_dry_run() -> None:
    """Only a missing gateway is tolerated in a dry run. A malformed declaration
    exits 2 and must not read as 'nothing to do'."""
    [plan] = [t for t in _flat(_job_tasks()) if "plan" in t.get("name", "").lower() and "command" in str(t)]
    assert "ignore_errors" not in plan
    rule = str(plan["failed_when"])
    assert "rc == 2" in rule, "exit 2 is the planner's refusal"
    assert "not ansible_check_mode" in rule, "any other failure still fails a real run"
