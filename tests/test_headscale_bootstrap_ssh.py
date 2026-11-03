"""The control-plane bootstrap account's keys: rendered only from SOPS, each limited to the control plane.

`ts-bridge connect --bootstrap-ssh` reaches Headscale through an SSH forward on the VPS
(VPN-ACL-015, #2862). `ssh_hardening` limits the account to that forward; the
`headscale` role creates the account and renders its `authorized_keys` from SOPS, one
`restrict,port-forwarding,permitopen=...` line per enrolled machine. The file is
declared whole, so removing a key from SOPS revokes it on the next deploy.

The role's own expressions are evaluated by Jinja as Ansible evaluates them, as in
`test_headscale_segments.py`.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env, task_runs

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/headscale"
TASKS = yaml.safe_load((ROLE / "tasks/bootstrap_identity.yml").read_text(encoding="utf-8"))
MAIN = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))

ED25519 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExampleEx client one"
CONTROL_PLANE = "vpn.kubelab.live:443"


def _env() -> Any:
    env = ansible_env(str(ROLE / "templates"))
    env.filters["dict2items"] = lambda d: [{"key": k, "value": v} for k, v in d.items()]
    return env


def _task(name: str) -> dict[str, Any]:
    return next(t for t in TASKS if t.get("name") == name)


def _vars(keys: dict[str, Any], user: str = "hs-bootstrap") -> dict[str, Any]:
    return {
        **DEFAULTS,
        "headscale_bootstrap_ssh_user": user,
        "headscale_bootstrap_ssh_keys": keys,
        "headscale_bootstrap_permit_open": CONTROL_PLANE,
    }


def _failed_checks(value: Any) -> list[str]:
    env = _env()
    checks = _task("Refuse a malformed bootstrap key")["assert"]["that"]
    variables = {**_vars({"client-1": value}), "item": {"key": "client-1", "value": value}}
    # Ansible stops at the first false condition, so a later one never sees a value
    # an earlier one refused (a regex test on a list would raise instead).
    for expr in checks:
        if not env.compile_expression(expr)(**variables):
            return [expr]
    return []


def _authorized_keys(keys: dict[str, Any]) -> str:
    content = _task("Render the bootstrap account's authorized_keys from SOPS")["copy"]["content"]
    return _env().from_string(content).render(**_vars(keys))


# --- a key is one public key, nothing else ---------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        ED25519,
        ED25519.rsplit(" ", 2)[0],  # no comment
        "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTY= c",
        "sk-ssh-ed25519@openssh.com AAAAGnNrLXNzaC1lZDI1NTE5QG9wZW5zc2guY29t laptop",
    ],
)
def test_a_well_formed_key_passes(value: str) -> None:
    assert not _failed_checks(value)


@pytest.mark.parametrize(
    "value",
    [
        'command="/bin/sh" ' + ED25519,  # options would widen what the key may do
        "restrict " + ED25519,
        ED25519 + "\n" + ED25519,  # two keys in one entry
        ED25519 + "\n",
        "ssh-ed25519",
        "ssh-ed25519 not*base64",
        "ssh-dss AAAAB3NzaC1kc3MAAACBAP",
        "",
        ["ssh-ed25519", "AAAA"],
        {"key": ED25519},
    ],
)
def test_a_malformed_key_is_refused(value: Any) -> None:
    assert _failed_checks(value)


def test_the_key_check_names_the_entry_and_never_the_key() -> None:
    task = _task("Refuse a malformed bootstrap key")

    assert task["loop_control"]["label"] == "{{ item.key }}"
    assert "item.value" not in task["assert"]["fail_msg"]


# --- the file: one restricted line per SOPS entry ---------------------------------


def test_each_key_gets_one_line_restricted_to_the_control_plane() -> None:
    other = ED25519.replace("client one", "client two")
    lines = _authorized_keys({"client-2": other, "client-1": ED25519}).splitlines()

    prefix = f'restrict,port-forwarding,permitopen="{CONTROL_PLANE}" '
    assert lines == [prefix + ED25519, prefix + other], "one line per key, ordered by entry name"


def test_a_key_absent_from_sops_is_absent_from_the_file() -> None:
    assert _authorized_keys({}) == ""


def test_the_file_is_root_owned_and_its_render_is_never_printed() -> None:
    task = _task("Render the bootstrap account's authorized_keys from SOPS")
    directory = _task("Create the bootstrap account's .ssh directory, owned by root")

    assert (task["copy"]["owner"], task["copy"]["group"], task["copy"]["mode"]) == ("root", "root", "0644")
    assert (directory["file"]["owner"], directory["file"]["mode"]) == ("root", "0755")
    assert task["no_log"] is True


def test_the_account_has_no_shell_and_no_password() -> None:
    account = _task("Create the bootstrap account")["ansible.builtin.user"]

    assert account["shell"] == "/usr/sbin/nologin"
    assert account["password"] == "!"
    assert "groups" not in account


def test_nothing_runs_without_a_declared_account() -> None:
    assert DEFAULTS["headscale_bootstrap_ssh_user"] == ""
    for task in TASKS:
        assert not task_runs(task, _vars({}, user="")), task["name"]
        assert task_runs(task, _vars({"client-1": ED25519})), task["name"]


def test_the_role_declares_the_account_before_the_retired_tls_teardown() -> None:
    names = [t.get("name") for t in MAIN]

    assert names.index("Declare the control-plane bootstrap account") < names.index(
        "Remove the retired certbot and nginx packages"
    )


# --- the playbooks: keys from SOPS, one destination for sshd and the keys ----------


def _play_role_vars(playbook: str, role: str) -> dict[str, Any]:
    plays = yaml.safe_load((REPO / f"infra/ansible/playbooks/{playbook}").read_text(encoding="utf-8"))
    roles = [r for p in plays for r in p.get("roles") or [] if isinstance(r, dict)]
    return next(r["vars"] for r in roles if r["role"].endswith(role))


def _expr(value: Any) -> str:
    return str(value).strip().removeprefix("{{").removesuffix("}}")


def _eval(value: Any, **variables: Any) -> Any:
    """A play var as Ansible resolves it: one expression keeps its type, anything else renders to text."""
    text = str(value).strip()
    if text.startswith("{{") and text.endswith("}}") and text.count("{{") == 1:
        return _env().compile_expression(_expr(text))(**variables)
    return _env().from_string(text).render(**variables)


def test_keys_reach_the_role_only_from_sops() -> None:
    expr = _expr(_play_role_vars("deploy-vps.yml", "headscale")["headscale_bootstrap_ssh_keys"])
    secrets = {"apps": {"services": {"core": {"headscale": {"bootstrap_ssh_keys": {"client-1": ED25519}}}}}}

    assert "secrets" in expr and "config." not in expr
    assert _env().compile_expression(expr)(secrets=secrets) == {"client-1": ED25519}
    assert _env().compile_expression(expr)(secrets={}) == {}


def _provision_forward(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or COMMON
    plays = yaml.safe_load((REPO / "infra/ansible/playbooks/provision.yml").read_text(encoding="utf-8"))
    task = next(
        t for p in plays for t in p.get("pre_tasks") or [] if "ssh_bootstrap_forward" in (t.get("set_fact") or {})
    )
    assert task_runs(task, {"group_names": ["vps"], "config": config})
    assert not task_runs(task, {"group_names": ["k3s_servers"], "config": config})
    fact = task["set_fact"]["ssh_bootstrap_forward"]
    # The VPS's inventory user is the cloud SSH user (generator_ansible.py, SSOT-014a).
    ssh_user = config["networking"]["ssh_users"]["cloud"]
    return {k: _eval(v, config=config, ansible_user=ssh_user) for k, v in fact.items()}


def test_sshd_and_the_keys_open_the_same_single_destination() -> None:
    play_vars = _play_role_vars("deploy-vps.yml", "headscale")
    keys_open = _eval(play_vars["headscale_bootstrap_permit_open"], config=COMMON)
    keys_user = _eval(play_vars["headscale_bootstrap_ssh_user"], config=COMMON)
    sshd = _provision_forward()

    domain = COMMON["apps"]["services"]["core"]["headscale"]["domain"]
    assert sshd["permit_open"] == keys_open == f"{domain}:443"
    assert sshd["user"] == keys_user == "hs-bootstrap"


def test_the_vps_ssh_user_forwards_nothing_once_its_clients_have_moved() -> None:
    assert _provision_forward()["transitional_users"] == []


def test_narrow_ssh_user_narrows_the_vps_ssh_user_when_a_client_still_needs_it() -> None:
    config = copy.deepcopy(COMMON)
    config["networking"]["vps"]["ssh_bootstrap"]["narrow_ssh_user"] = True

    assert _provision_forward(config)["transitional_users"] == [config["networking"]["ssh_users"]["cloud"]]
