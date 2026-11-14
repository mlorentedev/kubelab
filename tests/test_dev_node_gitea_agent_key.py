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


# The two guards below were in test_dev_node_npm_converges.py; they guard the forge
# key, not npm (ANSIBLE-037 review, F11).
def _tasks() -> list[dict]:
    """Every task in the role, including those nested in a block."""
    flat: list[dict] = []
    for task in yaml.safe_load(ROLE_TASKS.read_text(encoding="utf-8")):
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _task_named(name: str) -> dict:
    for task in _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r}")


def test_the_forge_key_is_looked_up_by_fingerprint() -> None:
    """The forge answers whether the key is registered; the role does not parse a list.

    The previous comparison ran `regex_replace(..., '\\2')` inside Jinja, which
    reads '\\2' as chr(2). No key ever matched, so every pass after the first
    POSTed the key again and failed on Gitea's 422 (ace2, 2026-10-01).
    """
    lookup = _task_named("Look up this node's key on each account it may be on")
    assert "/users/{{ item }}/keys?fingerprint=" in lookup["ansible.builtin.uri"]["url"], (
        "a fingerprint query on /user/keys is not restricted to an owner, so another account's copy would match"
    )
    assert lookup["loop"] == ["{{ dev_node_gitea_former_user }}", "{{ dev_node_gitea_user }}"], (
        "the register step reads results[1] as the agents' account; the loop order is load-bearing"
    )
    register = _task_named("Register this node's public key on the agents' account")
    when = " ".join(register["when"]) if isinstance(register["when"], list) else register["when"]
    assert "regex_replace" not in when
    assert "_gitea_keys.results[1].json" in when
    assert "selectattr('fingerprint'" in when, (
        "match the fingerprint on the answer too: a forge that ignored the filter "
        "would return every key, and any key would read as this node's"
    )
    assert register["changed_when"] == "_gitea_key_post.status == 201", "a POST that creates a key is a change"


def test_the_forge_key_lookup_survives_a_dry_run() -> None:
    """`--check` skips a `command` task, and the lookup templates its stdout."""
    lookup = _task_named("Look up this node's key on each account it may be on")
    assert lookup.get("check_mode") is False
    assert lookup.get("when") == "_gitea_key_fp.rc == 0"


def test_an_empty_credential_skips_loudly() -> None:
    """A loaded vault without the key must not give a silent, green, access-less node."""
    tasks = yaml.safe_load(ROLE_TASKS.read_text(encoding="utf-8"))
    names = [t.get("name") for t in tasks]
    notice = tasks[names.index("Say the forge block is skipped, and why")]
    block = tasks[names.index("Configure git access to the private forge")]
    assert notice["when"] == "dev_node_gitea_admin_password | length == 0"
    assert block["when"] == "dev_node_gitea_admin_password | length > 0", (
        "the notice must be the block's exact complement"
    )
    assert "SKIPPED" in notice["ansible.builtin.debug"]["msg"]


def test_an_existing_key_is_recommented_to_its_account() -> None:
    """`creates:` never revisits a key, so the comment is converged separately."""
    recomment = _task_named("Re-comment the key with the identity it is registered to")
    cmd = recomment["ansible.builtin.command"]
    assert "ssh-keygen -c" in cmd and "{{ dev_node_gitea_user }}@{{ inventory_hostname }}" in cmd
    assert "_gitea_key_comment.stdout" in recomment["when"], (
        "re-comment only on a mismatch, or it reports changed every run"
    )
    read = _task_named("Read the comment on this node's forge key")
    assert read["changed_when"] is False and read["check_mode"] is False
