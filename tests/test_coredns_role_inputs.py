"""The coredns role derives its own inputs, so no caller can leave one out (#1982).

Two playbooks run the role, and each used to copy its variables by hand. #1278
added `coredns_health_bind_ip` to deploy-dns.yml only, and `make provision
NODE=rpi4` failed on the template from then on. The role now reads the SSOT in
its defaults; these tests keep it that way.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import Environment, meta

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/coredns"
PLAYBOOKS = REPO / "infra/ansible/playbooks"
COMMON = REPO / "infra/config/values/common.yaml"
ANSIBLE = REPO / "infra/ansible"
INCLUDE_KEYS = ("include_role", "import_role", "ansible.builtin.include_role", "ansible.builtin.import_role")


def _defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text())


def _template_inputs() -> set[str]:
    env = Environment()
    names: set[str] = set()
    for path in (ROLE / "templates").glob("*.j2"):
        names |= meta.find_undeclared_variables(env.parse(path.read_text()))
    return names


def _callers() -> list[tuple[Path, dict, dict]]:
    """(playbook, play, role entry) for every play that runs the coredns role."""
    found = []
    for path in sorted(PLAYBOOKS.glob("*.yml")):
        for play in yaml.safe_load(path.read_text()) or []:
            for role in play.get("roles") or []:
                name = role.get("role", "") if isinstance(role, dict) else role
                if name.rstrip("/").endswith("roles/coredns"):
                    found.append((path, play, role if isinstance(role, dict) else {}))
    return found


def _is_coredns(name: object) -> bool:
    return isinstance(name, str) and name.rstrip("/").split("/")[-1] == "coredns"


def _references(node: object) -> int:
    """How many times a YAML tree runs the coredns role, by any spelling Ansible accepts."""
    count = 0
    if isinstance(node, dict):
        if _is_coredns(node.get("role")):
            count += 1
        for key in INCLUDE_KEYS:
            if isinstance(node.get(key), dict) and _is_coredns(node[key].get("name")):
                count += 1
        for item in node.get("roles") or [] if isinstance(node.get("roles"), list) else []:
            if _is_coredns(item):
                count += 1
        for value in node.values():
            count += _references(value)
    elif isinstance(node, list):
        for item in node:
            count += _references(item)
    return count


def _defaults_paths() -> set[str]:
    text = (ROLE / "defaults/main.yml").read_text()
    return set(re.findall(r"\{\{\s*common\.([a-z0-9_.]+)", text))


def test_the_guard_finds_the_template_inputs() -> None:
    inputs = _template_inputs()
    assert {"coredns_health_bind_ip", "staging_zones", "node_ips"} <= inputs, inputs


def test_every_template_input_has_a_default() -> None:
    missing = _template_inputs() - set(_defaults())
    assert not missing, f"the coredns templates read {sorted(missing)}, which the role does not define"


def test_both_playbooks_are_found() -> None:
    names = {path.name for path, _, _ in _callers()}
    assert {"deploy-dns.yml", "provision-rpi4.yml"} <= names, names


def test_no_caller_passes_its_own_copy() -> None:
    for path, _, role in _callers():
        assert not role.get("vars"), f"{path.name} passes vars to coredns; derive them in the role's defaults"


def test_every_caller_loads_common_as_the_defaults_expect() -> None:
    for path, play, _ in _callers():
        loads = [
            task
            for task in play.get("pre_tasks") or []
            if (task.get("include_vars") or task.get("ansible.builtin.include_vars") or {}).get("name") == "common"
        ]
        assert loads, f"{path.name} runs coredns without loading common.yaml as `common`"


def test_the_defaults_resolve_against_the_ssot() -> None:
    """Every `common.*` path the defaults read exists, so a renamed key fails here, not on the node."""
    common = yaml.safe_load(COMMON.read_text())
    for dotted in _defaults_paths():
        node = common
        for part in dotted.split("."):
            assert isinstance(node, dict) and part in node, f"common.{dotted} does not exist in common.yaml"
            node = node[part]


def test_every_reference_to_the_role_is_a_caller_these_tests_read() -> None:
    """A third caller via include_role, a short name, a .yaml file or another directory is still seen."""
    seen = 0
    for path in sorted(ANSIBLE.rglob("*.y*ml")):
        if ROLE in path.parents:
            continue
        for doc in yaml.safe_load_all(path.read_text()):
            seen += _references(doc)
    assert seen == len(_callers()), (
        f"{seen} references to the coredns role, {len(_callers())} of them play-level `roles:` entries "
        "in playbooks/*.yml; run it from a play's `roles:` so these tests can check the caller"
    )


def _get(tree: object, dotted: str) -> tuple[bool, object]:
    for part in dotted.split("."):
        if not isinstance(tree, dict) or part not in tree:
            return False, None
        tree = tree[part]
    return True, tree


def test_the_env_provision_rpi4_merged_agrees_with_common() -> None:
    """provision-rpi4 used to render from common merged with its pinned env; the role now reads common alone.

    That is only the same rendering while the pinned env overrides none of these
    paths with a different value.
    """
    [play] = yaml.safe_load((PLAYBOOKS / "provision-rpi4.yml").read_text())
    env = play["vars"]["_rpi4_env"]
    common = yaml.safe_load(COMMON.read_text())
    overlay = yaml.safe_load((COMMON.parent / f"{env}.yaml").read_text()) or {}
    for dotted in sorted(_defaults_paths()):
        overridden, value = _get(overlay, dotted)
        if overridden:
            assert value == _get(common, dotted)[1], (
                f"{env}.yaml sets {dotted} to {value!r}; the coredns role reads common's"
            )
