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
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
CONFIG: dict[str, Any] = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())
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
    plays = yaml.safe_load((PLAYBOOKS / f"provision-{node}.yml").read_text())
    (entry,) = [r for p in plays for r in p.get("roles") or [] if str(r.get("role", "")).endswith("/tailscale")]
    return {k: _render(v, config=CONFIG) if isinstance(v, str) else v for k, v in entry.get("vars", {}).items()}


def _up_command(node: str, key: str) -> str:
    template = _task("Build Tailscale up command")["set_fact"]["tailscale_up_cmd"]
    return " ".join(_render(template, **_play_vars(node), _tailscale_key=key).split())


def test_the_edge_rejoins_with_every_flag_its_play_declares() -> None:
    command = _up_command("rpi4", KEY).split()
    assert command[:3] == ["tailscale", "up", "--reset"]
    assert f"--login-server=https://{CONFIG['apps']['services']['core']['headscale']['domain']}" in command
    assert "--accept-dns=false" in command
    assert "--accept-routes=false" in command, "a LAN node must not take its own subnet route back"
    assert f"--advertise-routes={CONFIG['networking']['lan_cidr']}" in command
    assert f"--authkey={KEY}" in command


def test_the_edge_play_lets_the_role_mint() -> None:
    variables = _play_vars("rpi4")
    assert variables["tailscale_headscale_user_id"] == str(
        CONFIG["apps"]["services"]["core"]["headscale"]["infra_user_id"]
    )
    assert "tailscale_mint_key" not in variables, "minting is the rejoin's switch, not the play's"


def test_no_authkey_flag_without_a_key() -> None:
    assert "--authkey" not in _up_command("rpi4", "")


# --------------------------------------------------------------- the operator's side


def test_the_rejoin_runs_the_nodes_own_play() -> None:
    from toolkit.features.headscale_nodes import rejoin_playbook

    assert rejoin_playbook(PLAYBOOKS, "rpi4") == "provision-rpi4"


@pytest.mark.parametrize("node", ["rpi3", "no-such-node"])
def test_a_node_whose_play_cannot_rejoin_it_is_refused(node: str) -> None:
    """rpi3's play installs no tailscale role, so a rejoin there would do nothing and
    report success."""
    from toolkit.features.headscale_nodes import RejoinRefused, rejoin_playbook

    with pytest.raises(RejoinRefused, match=r"ERROR: .* WHY: .* FIX: "):
        rejoin_playbook(PLAYBOOKS, node)


def _invoke(node: str, run_exit: int = 0) -> tuple[Any, mock.MagicMock, mock.MagicMock]:
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
        generate.return_value = {"success": True}
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


def test_a_refused_node_runs_nothing() -> None:
    result, ansible_run, _ = _invoke("rpi3")
    assert result.exit_code == 1
    assert not ansible_run.called


def test_the_makefile_target_calls_the_command() -> None:
    makefile = (REPO / "Makefile").read_text()
    target = re.search(r"^headscale-rejoin:.*\n((?:\t.*\n)+)", makefile, re.M)
    assert target, "no headscale-rejoin target"
    assert "infra headscale rejoin --node $(NODE)" in target.group(1)
    assert "--env $(or $(filter staging prod,$(ENV)),prod)" in target.group(1), "the edge is provisioned against prod"
