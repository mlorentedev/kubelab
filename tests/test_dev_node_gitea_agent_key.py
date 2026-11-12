"""ANSIBLE-037 D1 amendment (#1075): ace2's forge key belongs to the agents' account.

An agent on ace2 pushes with the node's key. If that key sits on the machine
account, the push is attributed to the provisioning bot, which has team write on
every `personal/` repository. #2578 moved every agent git path to the agents'
account. So the role registers the key there instead.

The agents' token has no `write:user` scope, so it cannot add a key. The
superadmin adds it through the admin API, from the controller, and the
credential never reaches the node.

Gitea refuses a public key that another account already holds. So the role
removes the key from the machine account before it registers it on the agents'
account. Without that step, a node provisioned before this change would get a
422 on every run.

These tests are static. They read the playbook and the role, which are the
files that decide this. They need no cluster and no decryption.
"""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ACE2_PLAYBOOK = REPO_ROOT / "infra/ansible/playbooks/provision-ace2.yml"
ROLE_TASKS = REPO_ROOT / "infra/ansible/roles/dev_node/tasks/main.yml"


def _dev_node_vars() -> dict[str, str]:
    found: dict[str, str] = {}
    for play in yaml.safe_load(ACE2_PLAYBOOK.read_text(encoding="utf-8")) or []:
        for role in (play or {}).get("roles") or []:
            if isinstance(role, dict) and "dev_node" in str(role.get("role", "")):
                for name, value in (role.get("vars") or {}).items():
                    if isinstance(value, str):
                        found[name] = value.strip()
    return found


def _gitea_tasks() -> list[dict]:
    """The tasks inside the role's forge-access block, in order."""
    for task in yaml.safe_load(ROLE_TASKS.read_text(encoding="utf-8")) or []:
        if isinstance(task, dict) and "gitea" in (task.get("tags") or []) and "block" in task:
            return list(task["block"])
    raise AssertionError("dev_node has no tagged `gitea` block; the tests below would pass vacuously")


def _uri(task: dict) -> dict:
    return task.get("ansible.builtin.uri") or {}


def test_the_key_is_registered_on_the_agents_account() -> None:
    assert _dev_node_vars().get("dev_node_gitea_user", "").endswith("apps.auth.identities.agent }}"), (
        "ace2's forge key must go on the agents' account (ANSIBLE-037 D1 amendment, #1075). "
        "On the machine account an agent's push is attributed to the provisioning bot."
    )


def test_the_machine_account_is_where_the_key_is_removed_from() -> None:
    assert _dev_node_vars().get("dev_node_gitea_former_user", "").endswith("apps.auth.identities.machine }}")


def test_registration_uses_the_superadmin_and_never_the_bot_token() -> None:
    node_vars = _dev_node_vars()
    assert "dev_node_gitea_bot_token" not in node_vars, (
        "the bot token no longer registers anything on ace2, so the play must not resolve it"
    )
    assert node_vars.get("dev_node_gitea_admin_user", "").endswith("apps.auth.identities.superadmin }}")
    assert "gitea_secrets.apps.services.core.gitea.admin_password" in node_vars.get("dev_node_gitea_admin_password", "")
    assert "dev_node_gitea_bot_token" not in ROLE_TASKS.read_text(encoding="utf-8")


def test_every_forge_api_call_runs_on_the_controller_as_the_superadmin() -> None:
    calls = [t for t in _gitea_tasks() if _uri(t)]
    assert len(calls) >= 3, "expected a lookup on both accounts, a removal and a registration"
    for task in calls:
        uri = _uri(task)
        assert task.get("delegate_to") == "localhost", f"{task['name']}: the superadmin must stay off the node"
        assert task.get("no_log") is True, f"{task['name']}: carries the superadmin password"
        assert uri.get("force_basic_auth") is True, f"{task['name']}"
        assert "/user/keys" not in uri["url"], (
            f"{task['name']}: `/user/keys` acts on the caller, not the node's account"
        )


def test_the_key_leaves_the_machine_account_before_it_is_registered() -> None:
    tasks = _gitea_tasks()

    def index(method: str, account_var: str) -> int:
        for i, task in enumerate(tasks):
            uri = _uri(task)
            if uri.get("method") == method and f"/admin/users/{{{{ {account_var} }}}}/keys" in uri.get("url", ""):
                return i
        raise AssertionError(f"no {method} on /admin/users/{{{{ {account_var} }}}}/keys")

    assert index("DELETE", "dev_node_gitea_former_user") < index("POST", "dev_node_gitea_user"), (
        "Gitea refuses a key another account holds, so the removal must come first"
    )


def test_the_removal_loop_tolerates_a_missing_fingerprint() -> None:
    """`loop` is templated before `when`, so a `when` guard alone does not protect it."""
    removal = next(t for t in _gitea_tasks() if _uri(t).get("method") == "DELETE")
    assert "if _gitea_key_fp.rc == 0 else []" in removal["loop"], (
        "with no fingerprint, `stdout.split(' ')[1]` raises before `when` is read"
    )
