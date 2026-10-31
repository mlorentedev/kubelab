"""`make headscale-rejoin NODE=<n>` puts a node back on the mesh (NET-005 AC11, task 32).

The key is minted by the tailscale role, on the Headscale host, only when the node
is off the mesh and no key was passed in: single use and one hour, so a key that
outlives the registration opens nothing (the hermes sidecar's rule,
`agent_stack/tasks/hermes.yml`). It never reaches the toolkit, so it cannot reach
a log line there either.

`tailscale up --reset` drops every flag it is not given (tailscale/tailscale#5597),
so the command the role builds must carry each non-default flag the node's play
declares. The conditions are evaluated, not grepped: a `when:` is Jinja, and the
only honest test of one is to render it in each state it has to tell apart.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import typer
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "tailscale"
PLAYBOOKS = REPO / "infra" / "ansible" / "playbooks"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
CONFIG: dict[str, Any] = yaml.safe_load(
    (REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8")
)
KEY = "hskey-auth-test-0000"
RUNNING = {"rc": 0, "stdout": json.dumps({"BackendState": "Running"})}
STOPPED = {"rc": 0, "stdout": json.dumps({"BackendState": "NeedsLogin"})}
NO_DAEMON = {"rc": 1, "stdout": ""}


def _env() -> Any:
    env = ansible_env(str(ROLE))
    env.filters["from_json"] = json.loads
    return env


def _task(name: str) -> dict[str, Any]:
    (task,) = [t for t in TASKS if t.get("name", "").startswith(name)]
    return task


def _render(text: str, **variables: Any) -> str:
    return _env().from_string(text).render(**{**DEFAULTS, **variables}).strip()


def _true(expression: str, **variables: Any) -> bool:
    """A bare `when:` expression."""
    return _render("{{ (" + expression.strip() + ") | bool }}", **variables) == "True"


def _templated_true(template: str, **variables: Any) -> bool:
    """A value written as a `{{ }}` template, like a set_fact or a templated no_log."""
    return _render(template, **variables) == "True"


def _facts(status: dict[str, Any], minted: str = "", **variables: Any) -> dict[str, Any]:
    """Run the role's own fact tasks in order, the way Ansible would."""
    facts: dict[str, Any] = {**variables, "tailscale_status": status}
    running = _task("Hold whether the node is on the mesh")["set_fact"]["_tailscale_running"]
    facts["_tailscale_running"] = _templated_true(running, **facts)
    mint = _task("Mint a single-use pre-auth key")
    facts["_tailscale_mint"] = {"stdout": minted} if _true(mint["when"], **facts) else {"skipped": True}
    key = _task("Hold the key this run registers with")["set_fact"]["_tailscale_key"]
    facts["_tailscale_key"] = _render(key, **facts)
    return facts


# --------------------------------------------------------------------- the key


def test_the_minted_key_is_single_use_and_expires_within_an_hour() -> None:
    command = _task("Mint a single-use pre-auth key")["command"]
    assert "preauthkeys create" in command
    assert "--reusable" not in command, "a reusable key is a standing invitation to the mesh"
    assert "--expiration 1h" in command
    assert "--user {{ tailscale_headscale_user_id }}" in command


def test_the_key_is_minted_on_the_headscale_host() -> None:
    mint = _task("Mint a single-use pre-auth key")
    assert mint["delegate_to"] == "{{ tailscale_headscale_host }}"
    assert mint["become"] is False
    assert DEFAULTS["tailscale_headscale_host"] == "kubelab-vps"


@pytest.mark.parametrize(
    ("status", "flag", "passed", "mints"),
    [
        (STOPPED, True, "", True),
        (NO_DAEMON, True, "", True),
        (RUNNING, True, "", False),
        (STOPPED, False, "", False),
        (STOPPED, True, "hskey-auth-passed", False),
    ],
    ids=["off-mesh", "no-daemon", "on-mesh", "not-asked", "key-passed-in"],
)
def test_a_key_is_minted_only_when_asked_and_off_the_mesh(
    status: dict[str, Any], flag: bool, passed: str, mints: bool
) -> None:
    facts = _facts(status, KEY, tailscale_mint_key=flag, tailscale_auth_key=passed)
    assert ("stdout" in facts["_tailscale_mint"]) is mints


def test_minting_is_off_unless_the_rejoin_asks() -> None:
    """A provision before the portal login has no uplink: an unasked mint would turn
    the manual-instructions path into a red run."""
    assert DEFAULTS["tailscale_mint_key"] is False


def test_a_passed_in_key_wins_over_minting() -> None:
    """bee, ace1 and ace2 pass their own key as a role var, which outranks set_fact."""
    facts = _facts(STOPPED, KEY, tailscale_mint_key=True, tailscale_auth_key="hskey-auth-passed")
    assert facts["_tailscale_key"] == "hskey-auth-passed"


# ------------------------------------------------------------- the registration


@pytest.mark.parametrize(
    ("status", "passed", "registers"),
    [(STOPPED, "", True), (NO_DAEMON, "", True), (RUNNING, "", False), (RUNNING, "hskey-auth-passed", False)],
    ids=["off-mesh", "no-daemon", "on-mesh", "on-mesh-key-passed-in"],
)
def test_tailscale_up_runs_only_when_the_node_is_off_the_mesh(
    status: dict[str, Any], passed: str, registers: bool
) -> None:
    facts = _facts(status, KEY, tailscale_mint_key=True, tailscale_auth_key=passed)
    assert _true(_task("Register with Headscale")["when"], **facts) is registers


def test_without_a_key_it_falls_back_to_the_manual_instructions() -> None:
    facts = _facts(STOPPED, tailscale_mint_key=False)
    assert not _true(_task("Register with Headscale")["when"], **facts)
    assert _true(_task("Show manual auth instructions")["when"], **facts)


@pytest.mark.parametrize("name", ["Mint a single-use pre-auth key", "Hold the key this run registers with"])
def test_the_tasks_that_only_ever_hold_a_key_never_log(name: str) -> None:
    assert _task(name).get("no_log") is True


@pytest.mark.parametrize(
    "name", ["Build Tailscale up command", "Register with Headscale", "Wait for Tailscale registration"]
)
def test_the_tasks_that_may_hold_a_key_hide_it_and_only_it(name: str) -> None:
    """`-v` prints set_fact results, a failed command prints its `cmd`, and
    async_status returns the job's result, `cmd` included. Without a key there is
    nothing to hide, and the manual path keeps its logs."""
    no_log = _task(name).get("no_log")
    assert isinstance(no_log, str), f"{name!r} must decide no_log from the key"
    assert _templated_true(no_log, _tailscale_key=KEY)
    assert not _templated_true(no_log, _tailscale_key="")


# ----------------------------------------------- the flags (tailscale/tailscale#5597)


def _play_vars(node: str) -> dict[str, Any]:
    plays = yaml.safe_load((PLAYBOOKS / f"provision-{node}.yml").read_text(encoding="utf-8"))
    (entry,) = [r for p in plays for r in p.get("roles") or [] if str(r.get("role", "")).endswith("/tailscale")]
    return {k: _render(v, config=CONFIG) if isinstance(v, str) else v for k, v in entry.get("vars", {}).items()}


def _up_command(node: str, key: str) -> str:
    """The two set_facts in order: the flags, then the command around them."""
    flags = _render(_task("Build the Tailscale up flags")["set_fact"]["tailscale_up_flags"], **_play_vars(node))
    template = _task("Build Tailscale up command")["set_fact"]["tailscale_up_cmd"]
    return " ".join(_render(template, tailscale_up_flags=flags, _tailscale_key=key).split())


def test_the_edge_rejoins_with_every_flag_its_play_declares() -> None:
    command = _up_command("rpi4", KEY).split()
    assert command[:3] == ["tailscale", "up", "--reset"]
    assert f"--login-server=https://{CONFIG['apps']['services']['core']['headscale']['domain']}" in command
    assert "--accept-dns=false" in command
    assert "--accept-routes=false" in command, "a LAN node must not take its own subnet route back"
    assert f"--advertise-routes={CONFIG['networking']['lan_cidr']}" in command
    assert f"--authkey={KEY}" in command


@pytest.mark.parametrize("node", ["rpi4", "rpi3"])
def test_the_play_lets_the_role_mint(node: str) -> None:
    variables = _play_vars(node)
    assert variables["tailscale_headscale_user_id"] == str(
        CONFIG["apps"]["services"]["core"]["headscale"]["infra_user_id"]
    )
    assert "tailscale_mint_key" not in variables, "minting is the rejoin's switch, not the play's"


def test_no_authkey_flag_without_a_key() -> None:
    assert "--authkey" not in _up_command("rpi4", "")


def test_rpi3_rejoins_on_magicdns_and_takes_no_subnet_route() -> None:
    """rpi3's host resolves `*.staging` through MagicDNS (the note on `rpi3_services`'
    `docker_dns_servers`), and it sits on the lab Wi-Fi, not on `lan_cidr`: it routes
    nothing for the mesh and needs no route from it (#2685)."""
    command = _up_command("rpi3", KEY).split()
    assert command[:3] == ["tailscale", "up", "--reset"]
    assert f"--login-server=https://{CONFIG['apps']['services']['core']['headscale']['domain']}" in command
    assert "--accept-dns=true" in command
    assert "--accept-routes=false" in command
    assert not [flag for flag in command if flag.startswith("--advertise-routes")]


# ------------------------------------------------- the flags of a node on the mesh

# What each node's prefs read on 2026-10-26, through the role's own filter. rpi3 had
# drifted: its play declares --accept-routes=false and the node held true, because a
# Running node never reaches `tailscale up`.
LIVE_PREFS = {
    "rpi3": {"RouteAll": True, "CorpDNS": True, "AdvertiseRoutes": []},
    "rpi4": {"RouteAll": False, "CorpDNS": False, "AdvertiseRoutes": ["172.16.1.0/24"]},
    "ace1": {"RouteAll": False, "CorpDNS": True, "AdvertiseRoutes": []},
    "gcp1": {"RouteAll": True, "CorpDNS": True, "AdvertiseRoutes": []},
}


def _prefs_filter() -> str:
    """The Python the read task runs on the node, as written in the task."""
    command = " ".join(_task("Read the routing and DNS prefs")["shell"].split())
    (code,) = re.findall(r"python3 -I -c '(.+)'$", command)
    return code


def _converge_facts(node: str, live: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    """The play's vars, then the task's own `vars:` evaluated as Ansible does, to a
    list or a dict rather than to the text a plain render gives."""
    facts = {**_play_vars(node), **overrides, "_tailscale_running": True}
    facts["_tailscale_prefs"] = {"stdout": json.dumps(live or {})}
    for name, template in _task("Converge the flags of a node on the mesh")["vars"].items():
        (inner,) = re.findall(r"^\{\{(.+)\}\}$", template.strip(), re.DOTALL)
        facts[name] = json.loads(_render("{{ (" + inner + ") | tojson }}", **facts))
    return facts


def _drifted(node: str, live: dict[str, Any], **overrides: Any) -> bool:
    facts = _converge_facts(node, live, **overrides)
    return all(_true(condition, **facts) for condition in _task("Converge the flags of a node on the mesh")["when"])


def test_the_prefs_leave_the_node_as_three_fields_and_no_key() -> None:
    """`tailscale debug prefs` carries the node and machine keys under Persist."""
    prefs = {
        "RouteAll": True,
        "CorpDNS": True,
        "AdvertiseRoutes": ["172.16.1.0/24", "10.9.0.0/24"],
        "Persist": {"PrivateNodeKey": "privkey:secret-node-key", "OldPrivateNodeKey": "privkey:old"},
        "ControlURL": "https://vpn.example",
    }
    result = subprocess.run(
        [sys.executable, "-I", "-c", _prefs_filter()], input=json.dumps(prefs), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "RouteAll": True,
        "CorpDNS": True,
        "AdvertiseRoutes": ["10.9.0.0/24", "172.16.1.0/24"],
    }
    assert "privkey" not in result.stdout


@pytest.mark.parametrize(
    ("status", "reads"), [(RUNNING, True), (STOPPED, False), (NO_DAEMON, False)], ids=["on", "off", "no-daemon"]
)
def test_only_a_node_on_the_mesh_is_read_and_converged(status: dict[str, Any], reads: bool) -> None:
    """Off the mesh, `tailscale up` applies the whole set, so there is nothing to converge."""
    facts = _facts(status)
    assert _true(_task("Read the routing and DNS prefs")["when"], **facts) is reads
    assert _true(_task("Converge the flags of a node on the mesh")["when"][0], **facts) is reads


@pytest.mark.parametrize("status", [STOPPED, NO_DAEMON], ids=["off", "no-daemon"])
def test_off_the_mesh_the_converge_stops_before_it_reads_the_prefs(status: dict[str, Any]) -> None:
    """Ansible stops at the first false condition, and the task's `vars:` render only
    when a condition reaches them. The skipped read left no stdout, so a drift check
    placed ahead of the mesh check would fail every provision of a node off the mesh."""
    facts = {**_facts(status), "_tailscale_prefs": {"skipped": True, "changed": False}}
    for condition in _task("Converge the flags of a node on the mesh")["when"]:
        if not _true(condition, **facts):
            break
    else:
        pytest.fail("off the mesh, the converge would run")


@pytest.mark.parametrize(("node", "drifted"), [("rpi3", True), ("rpi4", False), ("ace1", False), ("gcp1", False)])
def test_a_node_is_converged_only_where_it_differs_from_its_play(node: str, drifted: bool) -> None:
    assert _drifted(node, LIVE_PREFS[node]) is drifted


@pytest.mark.parametrize(
    "live",
    [
        {"RouteAll": False, "CorpDNS": True, "AdvertiseRoutes": ["172.16.1.0/24"]},
        {"RouteAll": False, "CorpDNS": False, "AdvertiseRoutes": []},
        {"RouteAll": False, "CorpDNS": False, "AdvertiseRoutes": ["172.16.1.0/24", "10.9.0.0/24"]},
    ],
    ids=["dns", "route-dropped", "route-added"],
)
def test_each_flag_is_drift_on_its_own(live: dict[str, Any]) -> None:
    assert _drifted("rpi4", live)


def test_the_order_of_advertised_routes_is_not_drift() -> None:
    live = {"RouteAll": False, "CorpDNS": False, "AdvertiseRoutes": ["10.9.0.0/24", "172.16.1.0/24"]}
    assert not _drifted("rpi4", live, tailscale_advertise_routes="172.16.1.0/24, 10.9.0.0/24")


def _set_command(node: str) -> list[str]:
    return _render(_task("Converge the flags of a node on the mesh")["command"], **_converge_facts(node)).split()


def test_the_converge_sets_the_whole_set_without_logging_in_again() -> None:
    """`tailscale set` changes prefs in place. `up --reset` would re-authenticate,
    and a Running node holds no key to do it with."""
    command = _set_command("rpi4")
    assert command[:2] == ["tailscale", "set"]
    assert "--accept-dns=false" in command
    assert "--accept-routes=false" in command
    assert f"--advertise-routes={CONFIG['networking']['lan_cidr']}" in command
    assert not [flag for flag in command if flag.startswith(("--reset", "--authkey", "--login-server"))]


def test_a_node_that_declares_no_route_clears_any_it_advertises() -> None:
    """An empty value is what withdraws a route; leaving the flag out would keep it."""
    assert "--advertise-routes=" in _set_command("rpi3")


def _roles(playbook: Path) -> list[dict[str, Any]]:
    return [
        r
        for p in yaml.safe_load(playbook.read_text(encoding="utf-8")) or []
        for r in p.get("roles") or []
        if isinstance(r, dict)
    ]


def _named(role: dict[str, Any]) -> str:
    return str(role.get("role", "")).rstrip("/").split("/")[-1]


@pytest.mark.parametrize(
    "playbook",
    [p for p in sorted(PLAYBOOKS.glob("provision-*.yml")) if any(_named(r) == "tailscale" for r in _roles(p))],
    ids=lambda p: p.stem,
)
def test_a_rejoin_pins_headscale_before_it_runs_up(playbook: Path) -> None:
    """A node off the mesh may still point its resolver at MagicDNS, which answers
    nothing then: `--tags tailscale` has to reach dns_resilience's /etc/hosts line for
    the login server first (#1259). The role itself needs the tag as much: its tasks
    carry none, so without it the rejoin runs the pin alone and reports success."""
    names = [_named(r) for r in _roles(playbook)]
    assert "dns_resilience" in names, f"{playbook.name} runs tailscale without pinning Headscale"
    pin = _roles(playbook)[names.index("dns_resilience")]
    assert names.index("dns_resilience") < names.index("tailscale")
    assert "tailscale" in pin.get("tags", []), "a rejoin runs --tags tailscale and would skip the pin"
    role = _roles(playbook)[names.index("tailscale")]
    assert "tailscale" in role.get("tags", []), "a rejoin runs --tags tailscale and would skip the role"


# --------------------------------------------------------------- the operator's side


@pytest.mark.parametrize("node", ["rpi4", "rpi3"])
def test_the_rejoin_runs_the_nodes_own_play(node: str) -> None:
    from toolkit.features.headscale_nodes import rejoin_playbook

    assert rejoin_playbook(PLAYBOOKS, node) == f"provision-{node}"


@pytest.mark.parametrize("play", ["without-the-role", None], ids=["no-tailscale-role", "no-play"])
def test_a_node_whose_play_cannot_rejoin_it_is_refused(tmp_path: Path, play: str | None) -> None:
    """A play without the tailscale role would run nothing under `--tags tailscale`
    and report success."""
    from toolkit.features.headscale_nodes import RejoinRefused, rejoin_playbook

    if play:
        (tmp_path / "provision-node.yml").write_text(
            "- hosts: node\n  roles:\n    - role: ../roles/base_system\n", encoding="utf-8"
        )
    with pytest.raises(RejoinRefused, match=r"ERROR: .* WHY: .* FIX: "):
        rejoin_playbook(tmp_path, "node")


def _invoke(node: str, run_exit: int = 0, restored: bool = True) -> tuple[Any, mock.MagicMock, mock.MagicMock]:
    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    def run(**_: Any) -> None:
        if run_exit:
            raise typer.Exit(run_exit)

    with (
        mock.patch("toolkit.cli.infra.ansible_run", side_effect=run) as ansible_run,
        mock.patch("toolkit.features.generator_ansible.ansible_generator.generate") as generate,
        mock.patch("subprocess.run", side_effect=AssertionError("the toolkit must not reach Headscale")),
    ):
        generate.return_value = {"success": restored, "error": "the generator failed"}
        result = CliRunner().invoke(app, ["headscale", "rejoin", "--node", node, "--env", "prod"])
    return result, ansible_run, generate


def test_the_command_runs_the_tailscale_role_over_the_lan_and_asks_it_to_mint() -> None:
    result, ansible_run, _ = _invoke("rpi4")
    assert result.exit_code == 0, result.output
    kwargs = ansible_run.call_args.kwargs
    assert kwargs["playbook"] == "provision-rpi4"
    assert kwargs["env"] == "prod"
    assert kwargs["tags"] == "tailscale"
    assert kwargs["bootstrap"] is True, "a node off the mesh answers only on its LAN address"
    assert kwargs["extra_vars"] == "tailscale_mint_key=true"
    assert kwargs["require_fresh"] is True


@pytest.mark.parametrize("run_exit", [0, 1])
def test_the_mesh_inventory_is_restored_whatever_the_run_did(run_exit: int) -> None:
    result, _, generate = _invoke("rpi4", run_exit)
    assert result.exit_code == run_exit
    assert generate.call_args_list[-1] == mock.call("prod")


@pytest.mark.parametrize(("run_exit", "expected"), [(0, 1), (2, 2)], ids=["clean-run", "failed-run"])
def test_a_failed_restore_fails_the_command_without_hiding_why_the_run_failed(run_exit: int, expected: int) -> None:
    """The restore runs in `finally`: an exit raised there would replace the run's own."""
    result, _, _ = _invoke("rpi4", run_exit, restored=False)
    assert result.exit_code == expected


def test_a_refused_node_runs_nothing() -> None:
    result, ansible_run, _ = _invoke("no-such-node")
    assert result.exit_code == 1
    assert not ansible_run.called


def test_the_makefile_target_calls_the_command() -> None:
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    target = re.search(r"^headscale-rejoin:.*\n((?:\t.*\n)+)", makefile, re.M)
    assert target, "no headscale-rejoin target"
    assert "infra headscale rejoin --node $(NODE)" in target.group(1)
    assert "--env $(or $(filter staging prod,$(ENV)),prod)" in target.group(1), "the edge is provisioned against prod"
