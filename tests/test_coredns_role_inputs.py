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
    text = (ROLE / "defaults/main.yml").read_text()
    for dotted in set(re.findall(r"\{\{\s*common\.([a-z0-9_.]+)", text)):
        node = common
        for part in dotted.split("."):
            assert isinstance(node, dict) and part in node, f"common.{dotted} does not exist in common.yaml"
            node = node[part]
