"""hermes-kubelab's config.yaml (ADR-068 D2, spec AI-009-hermes-ace2 PR 3, AC3).

The posture is the config: commands run in a sandbox container, approvals are
manual and fail closed, and the deny list blocks what the vault's guardrails
name. Each is asserted on the rendered file, and the deny list by what it
blocks, because a glob nobody runs against a command is a guard nobody checked.
"""

from __future__ import annotations

import fnmatch
import itertools
import re
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from tests.test_agent_stack_role import _template_task, _tasks

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
DENYLIST = ROLE / "files/guardrails-denylist.yaml"
COMMON = REPO / "infra/config/values/common.yaml"
RULES = yaml.safe_load(DENYLIST.read_text())["rules"]


def _render(name: str, **overrides: object) -> str:
    from tests.test_agent_stack_role import _resolved

    from tests.test_agent_stack_role import _environment

    env = _environment()
    return env.get_template(name).render(**{**_resolved(env), **overrides})


def _config(**overrides: object) -> dict:
    return yaml.safe_load(_render("hermes-config.yaml.j2", **overrides))


def _blocked(command: str, globs: list[str]) -> bool:
    """Hermes' own match: fnmatchcase over the whole command, both sides lowercased
    (v2026.9.24 `tools/approval_floors.py::_match_user_deny_rule`)."""
    return any(fnmatch.fnmatchcase(command.lower().strip(), g.lower()) for g in globs)


# --------------------------------------------------------------------------- the deny list


@pytest.mark.parametrize("rule", RULES, ids=[r["why"][:40] for r in RULES])
def test_each_rule_blocks_what_it_names_and_nothing_it_allows(rule: dict) -> None:
    for command in rule["blocks"]:
        assert _blocked(command, rule["globs"]), f"{command!r} runs: no glob of this rule matches it"
    for command in rule["allows"]:
        assert not _blocked(command, rule["globs"]), f"{command!r} is blocked, but the rule allows it"


@pytest.mark.parametrize("rule", RULES, ids=[r["why"][:40] for r in RULES])
def test_each_rule_keeps_the_meaning_of_its_vault_regex(rule: dict) -> None:
    """The conversion is faithful: the regex the vault confirmed matches the same
    commands. A rule may narrow its origin to ace2's paths with `origin_blocks`."""
    origin = re.compile(rule["origin"])
    for command in rule.get("origin_blocks", rule["blocks"]):
        assert origin.search(command), f"the vault regex does not block {command!r}: the example is wrong"
    for command in rule["allows"]:
        assert not origin.search(command), f"the vault regex blocks {command!r}, so allowing it widens the rule"


def test_the_rendered_deny_list_is_every_glob_of_the_file() -> None:
    globs = list(itertools.chain.from_iterable(r["globs"] for r in RULES))
    assert _config()["approvals"]["deny"] == globs


def test_the_role_reads_the_deny_list_from_that_file() -> None:
    """The tests above inject RULES; this pins that the role reads the same file."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert "role_path ~ '/files/guardrails-denylist.yaml'" in defaults["agent_stack_deny_rules"]
    assert defaults["agent_stack_deny_rules"].rstrip("} ").endswith(".rules")


# --------------------------------------------------------------------------- the posture


def test_commands_run_in_a_sandbox_that_receives_no_host_secret() -> None:
    terminal = _config()["terminal"]
    assert terminal["backend"] == "docker"
    assert terminal["docker_forward_env"] == [], "a forwarded variable is readable by every command"


def test_the_sandbox_has_no_network_until_it_has_its_own_tailnet_identity() -> None:
    """Through the rootless daemon a sandbox leaves as ace2, whose tailnet identity is
    the admin's and matches every allow rule (measured 2026-10-06: the VPS's :22 and
    :6443, both K3s APIs and Gitea answered). `false` is `--network=none`."""
    assert _config()["terminal"]["docker_network"] is False


def test_approvals_are_manual_and_fail_closed() -> None:
    approvals = _config()["approvals"]
    assert approvals["mode"] == "manual"
    assert approvals["timeout"] == 300
    # Nobody answers a scheduled job or an API call, so they deny instead of waiting.
    assert approvals["cron_mode"] == "deny"
    assert approvals["unattended_mode"] == "deny"


@pytest.mark.parametrize(
    "overrides",
    [{}, {"agent_stack_nan_api_key": ""}, {"tailscale_ip": "100.64.0.99"}],
    ids=["configured", "no-key", "other-address"],
)
def test_no_role_input_turns_approvals_off(overrides: dict) -> None:
    """`approvals.mode: off` is how hermes-nan ran, and ADR-068 D2 forbids it here.
    Unquoted, YAML reads it as `False`, so the check is equality, not `!= "off"`."""
    assert _config(**overrides)["approvals"]["mode"] == "manual"


def test_no_secret_is_written_into_the_config() -> None:
    """The NaN key lives in the `.env` (0600); config.yaml is read by the agent's tools."""
    text = yaml.safe_dump(_config())
    assert "nan-key-sentinel" not in text


def test_scheduled_and_delegated_work_runs_on_the_unmetered_model() -> None:
    """ADR-068 D7: the key is PR-Agent's, so only an interactive turn draws a quota."""
    config = _config()
    unmetered = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]["models"]["unmetered"]
    assert config["cron"]["model"] == unmetered
    assert config["delegation"]["model"] == unmetered
    assert config["cron"]["catch_up_missed"] is True


def test_the_key_is_named_in_the_config_and_held_only_in_the_env_file() -> None:
    config = _config()
    assert config["model"]["key_env"] == "NAN_API_KEY"
    env = dict(line.split("=", 1) for line in _render("hermes.env.j2").splitlines() if line and line[0] != "#")
    assert env["NAN_API_KEY"] == "nan-key-sentinel"
    assert env["API_SERVER_KEY"] == "hermes-api-key-sentinel", "the API refuses to start without a key"


# --------------------------------------------------------------------------- the gateway


def _gateway() -> dict:
    return yaml.safe_load(_render("compose-hermes.yml.j2"))["services"]["hermes"]


def test_the_gateway_drives_the_agents_own_daemon() -> None:
    from tests.test_agent_stack_role import _context as role_context

    uid = role_context()["_agent_stack_agent_uid"]
    host_sides = [v.split(":")[0] for v in _gateway()["volumes"]]
    assert f"/run/user/{uid}/docker.sock" in host_sides
    assert not {"/var/run/docker.sock", "/run/docker.sock"} & set(host_sides), "that socket is root on ace2"


def test_the_data_directory_has_the_same_path_on_both_sides() -> None:
    """The gateway names sandbox mounts by its own path; the daemon resolves them on the host."""
    gateway = _gateway()
    home = gateway["environment"]["HERMES_HOME"]
    assert f"{home}:{home}" in gateway["volumes"]


def test_the_api_is_published_on_loopback_only() -> None:
    ports = _gateway()["ports"]
    assert ports and all(str(p).startswith("127.0.0.1:") for p in ports), ports


def test_the_env_file_is_private_never_logged_and_outside_the_container() -> None:
    task = _template_task("hermes.env.j2")
    spec = task["ansible.builtin.template"]
    assert spec["mode"] == "0600"
    assert spec["owner"] == "{{ agent_stack_agent_user }}"
    assert task.get("no_log") is True
    gateway = _gateway()
    home = gateway["environment"]["HERMES_HOME"]
    [env_file] = gateway["env_file"]
    assert not env_file.startswith(home + "/"), "the agent's tools could read the keys"


def test_the_agent_cannot_rewrite_its_own_config() -> None:
    """At every start the image hands `$HERMES_HOME/config.yaml` to its runtime user
    and may migrate it (measured on ace2, 2026-10-06: `534287:534287 640` after the
    first start, and the next provision reported the file changed). So the config
    lives outside the data directory and is mounted over that path read-only."""
    from tests.test_agent_stack_role import _context as role_context

    spec = _template_task("hermes-config.yaml.j2")["ansible.builtin.template"]
    assert spec["dest"] == "{{ agent_stack_hermes_config }}"
    gateway = _gateway()
    home = gateway["environment"]["HERMES_HOME"]
    mounts = {v.rsplit(":", 2)[1]: v for v in gateway["volumes"] if v.endswith(":ro")}
    assert f"{home}/config.yaml" in mounts, "the gateway's config must be a read-only mount"
    source = mounts[f"{home}/config.yaml"].split(":", 1)[0]
    assert not source.startswith(home + "/"), "a source inside the data directory is the image's to rewrite"
    assert source.startswith(role_context()["agent_stack_agent_user"].join(("/var/lib/", "/")))


def test_hermes_is_not_deployed_without_the_inference_key_and_is_taken_down() -> None:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert "agent_stack_nan_api_key | length > 0" in defaults["agent_stack_hermes_configured"]
    gate = "agent_stack_hermes_configured | bool"
    [deploy] = [t for t in _tasks() if t.get("name") == "Deploy hermes-kubelab"]
    assert deploy["when"] == gate
    [stop] = [t for t in _tasks() if t.get("name") == "Stop hermes-kubelab when it is not configured"]
    assert stop["when"] == f"not ({gate})"


def test_every_provision_reads_the_deny_list_back_through_the_running_gateway() -> None:
    """A config Hermes failed to load leaves the list empty and the gateway running."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    evaluate = defaults["_agent_stack_hermes_evaluate"]
    assert evaluate[:6] == ["docker", "exec", "-u", "hermes", "hermes-kubelab", "hermes"]
    # The env type follows the mount: test_hermes_vault_sync proves which one.
    assert evaluate[6:] == ["approvals", "test", "--env-type", "{{ _agent_stack_hermes_env_type }}", "--json", "--"]
    checks = {t["name"]: t for t in _tasks() if "_agent_stack_hermes_evaluate" in str(t.get("ansible.builtin.command"))}
    refused = checks["Evaluate a command each deny rule must refuse"]
    assert "_agent_stack_hermes_refused_verdicts" in refused["failed_when"]
    allowed = checks["Evaluate every command the deny rules let through"]
    assert "_agent_stack_hermes_passed_verdicts" in allowed["failed_when"]
    # A refusal is never read as a pass, nor a pass as a refusal.
    assert defaults["_agent_stack_hermes_refused_verdicts"] == ["user-deny", "hardline-deny"]
    assert defaults["_agent_stack_hermes_passed_verdicts"] == ["allow", "ask-approval"]
