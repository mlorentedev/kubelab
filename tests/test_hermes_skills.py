"""The managed skills of hermes-kubelab (spec AI-012 AC9).

The vault's cross-agent skills the agent is given are declared once, copied by the
role from the root-owned vault mirror, and reach the gateway through Hermes's own
`skills.external_dirs`, mounted read-only. Each claim is asserted on what the role
renders or runs, not on the comment that describes it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.test_agent_stack_role import _environment, _resolved
from tests.test_hermes_config import HERMES, _config, _render

ROLE = Path(__file__).resolve().parent.parent / "infra/ansible/roles/agent_stack"
SKILLS = HERMES["skills"]
# The same path on the host and in the gateway: the sandbox's `docker run` is answered by the
# host's daemon, which resolves a bind source on the HOST. `/managed-skills` existed only inside
# the gateway, and every sandbox (terminal, read_file, search_files) failed with exit 126.
MOUNT = "/var/lib/hermes-kubelab/hermes-skills"


def _flat(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for task in items:
        out.append(task)
        out.extend(_flat(task.get("block", [])))
    return out


def _hermes_tasks() -> list[dict]:
    return _flat(yaml.safe_load((ROLE / "tasks/hermes.yml").read_text()))


def _task(name: str) -> dict:
    [task] = [t for t in _hermes_tasks() if t.get("name") == name]
    return task


def _compose(**overrides: object) -> str:
    return _render("compose-hermes.yml.j2", **{"agent_stack_vault_configured": True, **overrides})


def test_the_declared_skills_are_names_of_one_directory_each() -> None:
    assert SKILLS, "an empty manifest would make the whole mechanism a no-op nobody notices"
    assert len(SKILLS) == len(set(SKILLS)), "a skill declared twice is copied twice"
    for name in SKILLS:
        assert name == Path(name).name and not name.startswith("."), f"{name!r} is not a plain directory name"


def test_the_gateway_reads_the_managed_skills_as_an_external_directory() -> None:
    config = _config(agent_stack_vault_configured=True)
    assert config["skills"]["external_dirs"] == [MOUNT]


def test_the_gateway_sees_the_skills_at_the_path_the_host_daemon_will_resolve() -> None:
    """Hermes copies an external dir into each sandbox as `-v <dir>:...`, so the dir is a host path."""
    [volume] = [v for v in yaml.safe_load(_compose())["services"]["hermes"]["volumes"] if v.startswith(MOUNT)]
    source, target, mode = volume.split(":")
    assert source == target == MOUNT and mode == "ro"


def test_without_the_vault_there_is_no_external_directory_to_point_at() -> None:
    """The mount does not exist either, and Hermes refuses an external dir that is not there."""
    config = _config(agent_stack_vault_configured=False)
    assert isinstance(config["skills"], dict), "a mapping, never a bare key that parses as null"
    assert "external_dirs" not in config["skills"]
    assert MOUNT not in _compose(agent_stack_vault_configured=False)


def test_the_ported_harness_cannot_repoint_the_external_directory() -> None:
    hermes = {**HERMES, "agent_config": {**HERMES["agent_config"], "skills": {"external_dirs": ["/elsewhere"]}}}
    config = _config(agent_stack_vault_configured=True, agent_stack_hermes=hermes)
    assert config["skills"]["external_dirs"] == [MOUNT]


def test_a_ported_skills_section_holding_only_the_directory_renders_empty_not_null() -> None:
    hermes = {**HERMES, "skills": [], "agent_config": {**HERMES["agent_config"], "skills": {"external_dirs": ["/x"]}}}
    assert _config(agent_stack_vault_configured=True, agent_stack_hermes=hermes)["skills"] == {}


def test_the_ported_skills_keys_other_than_the_directory_still_render() -> None:
    hermes = {**HERMES, "agent_config": {**HERMES["agent_config"], "skills": {"guard_agent_created": True}}}
    config = _config(agent_stack_vault_configured=True, agent_stack_hermes=hermes)
    assert config["skills"] == {"external_dirs": [MOUNT], "guard_agent_created": True}


def test_the_skills_mount_is_read_only_and_comes_from_the_root_owned_copy() -> None:
    env = _environment()
    resolved = _resolved(env, agent_stack_vault_configured=True)
    source = resolved["agent_stack_hermes_skills"]
    assert f"- {source}:{MOUNT}:ro" in _compose()


def test_the_mount_is_dropped_when_no_skill_is_declared() -> None:
    hermes = {**HERMES, "skills": []}
    assert MOUNT not in _compose(agent_stack_hermes=hermes)
    config = _config(agent_stack_vault_configured=True, agent_stack_hermes=hermes)
    assert isinstance(config["skills"], dict) and "external_dirs" not in config["skills"]


def test_the_copy_is_root_owned_so_the_agent_cannot_rewrite_what_it_uses() -> None:
    directory = _task("Create the managed skills directory")["ansible.builtin.file"]
    copy = _task("Install each declared skill")["ansible.builtin.copy"]
    for spec in (directory, copy):
        assert spec["owner"] == "root" and spec["group"] == "root"
    assert copy["remote_src"] is True
    assert "w" not in copy["mode"].split(",")[1], "group and others get no write bit"


def test_the_skills_come_from_the_vault_mirror_not_from_the_agents_clone() -> None:
    """The agent holds the clone's token and writes its zone; the mirror is root's."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["agent_stack_hermes_skills_source"].startswith("{{ agent_stack_vault_mirror }}/")


def test_a_declared_skill_the_mirror_lacks_fails_the_provision() -> None:
    names = [t.get("name") for t in _hermes_tasks()]
    assert names.index("Look for each declared skill in the vault mirror") < names.index(
        "Refuse a declared skill the vault mirror does not hold"
    )
    refuse = _task("Refuse a declared skill the vault mirror does not hold")
    assert refuse["ansible.builtin.assert"]["that"] == "item.stat.exists"


def test_the_skills_are_installed_before_the_gateway_starts() -> None:
    """A missing mount source is created by Docker, owned by root; the order is the guard."""
    names = [t.get("name") for t in _hermes_tasks()]
    assert names.index("Install each declared skill") < names.index("Render the hermes-kubelab Compose project")


def test_a_skill_no_longer_declared_is_removed_from_the_node() -> None:
    removal = _task("Remove managed skills no longer declared")
    assert removal["ansible.builtin.file"]["state"] == "absent"
    assert "reject" in removal["loop"], "only what the declaration lacks is removed"


def test_the_running_gateway_is_asked_for_its_skills_and_refused_a_write() -> None:
    listed = _task("Read the managed skills back through the running gateway")
    assert listed["changed_when"] is False
    written = _task("Try to write into the managed skills as the gateway's user")
    assert written["failed_when"] == "_agent_stack_hermes_skills_write.rc == 0", "a write that succeeds fails the run"
    assert written["ansible.builtin.command"]["argv"][-1] == "{{ agent_stack_hermes_skills_mount }}/.write-probe"


# --------------------------------------------------------------------------- the live read-back

LISTING = [
    "┃ Name             ┃ Category         ┃ Source   ┃ Trust   ┃ Status            ┃",
    "│ insights         │                  │ external │ local   │ enabled           │",
    "│                  │                  │          │         │ /insights         │",
    "│ systematic-debu… │ software-develo… │ builtin  │ builtin │ enabled           │",
    "│ a-very-long-ext… │                  │ external │ local   │ enabled           │",
]


def _readback_fails(declared: list[str], listing: list[str], rc: int = 0) -> bool:
    """The read-back's own `failed_when`, evaluated with the Ansible filters and tests it uses."""
    import re

    from jinja2 import Environment

    env = Environment()
    env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(pattern, repl.replace("\\1", r"\1"), value)
    env.tests["search"] = lambda value, pattern: re.search(pattern, value) is not None
    env.filters["difference"] = lambda left, right: [item for item in left if item not in right]
    expression = _task("Read the managed skills back through the running gateway")["failed_when"]
    listed = {"rc": rc, "stdout_lines": listing}
    context = {"agent_stack_hermes": {"skills": declared}, "_agent_stack_hermes_skills_listed": listed}
    return env.from_string("{{ " + expression.strip() + " }}").render(**context) == "True"


def test_an_external_skill_in_the_listing_passes() -> None:
    assert not _readback_fails(["insights"], LISTING)


def test_a_name_the_image_ships_as_a_built_in_fails_even_though_it_is_listed() -> None:
    """The vault's copy would be installed and never read; the name alone is in the listing."""
    assert _readback_fails(["systematic-debugging"], LISTING)


def test_a_declared_skill_missing_from_the_listing_fails() -> None:
    assert _readback_fails(["insights", "audit"], LISTING)


def test_a_long_name_is_compared_the_way_the_table_cuts_it() -> None:
    assert not _readback_fails(["a-very-long-external-skill"], LISTING)


def test_a_failing_command_fails_the_read_back() -> None:
    assert _readback_fails(["insights"], LISTING, rc=1)
