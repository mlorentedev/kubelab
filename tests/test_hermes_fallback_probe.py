"""The fallback proof lives in the role (spec AI-018, closing AI-012 AC2's manual step).

A check whose injected fault cannot reach the code path passes by construction
(lesson-574), so the probe is the role's task: a throwaway gateway with NaN failed on
purpose, whose own log is read for the event it was meant to cause.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_hermes_fallback import KEY, _render

ROLE = Path(__file__).resolve().parent.parent / "infra/ansible/roles/agent_stack"


def _flat(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for task in items:
        out.append(task)
        for key in ("block", "always", "rescue"):
            out.extend(_flat(task.get(key, [])))
    return out


def _probe() -> list[dict]:
    return _flat(yaml.safe_load((ROLE / "tasks/hermes_fallback_probe.yml").read_text()))


def _task(name: str) -> dict:
    [task] = [t for t in _probe() if t.get("name") == name]
    return task


def _text(task: dict) -> str:
    return json.dumps(task, sort_keys=True)


def test_the_proof_is_off_unless_a_run_asks_for_it() -> None:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["agent_stack_fallback_probe"] is False
    outer = yaml.safe_load((ROLE / "tasks/hermes_fallback_probe.yml").read_text())[0]
    assert "agent_stack_fallback_probe | bool" in outer["when"]
    assert "ansible_check_mode" in outer["when"], "a dry run starts no gateway"


def test_the_proof_runs_after_the_gateway_is_reconciled() -> None:
    hermes = yaml.safe_load((ROLE / "tasks/hermes.yml").read_text())
    imports = [t["ansible.builtin.import_tasks"] for t in _flat(hermes) if "ansible.builtin.import_tasks" in t]
    assert imports[-1] == "hermes_fallback_probe.yml"


def test_the_primary_is_failed_in_a_gateway_that_touches_nothing_live() -> None:
    create = _text(_task("Create the probe gateway"))
    assert "NAN_API_KEY=sk-deliberately-invalid" in create
    for emptied in ("SLACK_BOT_TOKEN=", "SLACK_APP_TOKEN=", "SLACK_ALLOWED_USERS=", "API_SERVER_ENABLED=false"):
        assert f"'{emptied}'" in create, f"{emptied} must be set for the probe"
    assert "HERMES_HOME=" in create and "agent_stack_fallback_probe_home" in create, "its own home, not the live one"
    assert ":ro" in create, "the probe's config is mounted read-only"
    assert "agent_stack_fallback_probe_config" in create and "agent_stack_hermes_config" not in create
    assert "agent_stack_hermes_home" not in create, "the live data directory is never mounted"
    assert "--env-file" in create, "the fallback key comes from the live env file"


def test_the_credential_copy_never_reaches_the_nodes_disk_or_the_log() -> None:
    copy = _task("Give the probe a copy of the live credential pool")
    cmd = copy["ansible.builtin.shell"]["cmd"]
    assert "docker cp hermes-kubelab:" in cmd and "docker cp - " in cmd, "streamed container to container"
    assert copy["no_log"] is True
    assert "slurp" not in _text({"t": _probe()}) and "fetch" not in _text({"t": _probe()})


def test_the_probe_is_removed_however_the_run_ends() -> None:
    outer = yaml.safe_load((ROLE / "tasks/hermes_fallback_probe.yml").read_text())[0]
    always = _flat(outer["always"])
    assert any("rm" in _text(t) and "agent_stack_fallback_probe_name" in _text(t) for t in always)


def test_the_assertion_reads_the_event_not_just_the_answer() -> None:
    check = _task("Check the turn moved to Haiku and touched nothing live")
    that = "\n".join(check["ansible.builtin.assert"]["that"])
    assert "Fallback activated" in that
    assert "pong" in that
    assert "agent_stack_fallback_probe_slack_pattern" in that and "not (" in that, "no Slack connection opened"
    assert "anthropic" in that


def test_the_probes_own_config_carries_the_live_chain_and_nothing_else() -> None:
    """The probe cannot prove a chain it does not share with the gateway."""
    live = yaml.safe_load(_render("hermes-config.yaml.j2", **KEY))
    probe = yaml.safe_load(_render("hermes-fallback-probe-config.yaml.j2", **KEY))
    assert set(probe) == {"model", "fallback_providers"}
    assert probe["fallback_providers"] == live["fallback_providers"]
    assert {k: probe["model"][k] for k in ("provider", "base_url", "key_env", "default")} == {
        k: live["model"][k] for k in ("provider", "base_url", "key_env", "default")
    }


def test_the_probe_reads_the_event_where_the_gateway_writes_it() -> None:
    """The line is in HERMES_HOME's log files, not on the container's stdout (measured on ace2)."""
    read = _text(_task("Read the probe's log"))
    assert "/logs/*.log" in read
