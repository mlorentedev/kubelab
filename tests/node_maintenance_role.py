"""Resolve the node_maintenance role's defaults and render its templates the way
Ansible would, for one host's group membership.

The role's defaults are not constants: whether the CI reclaim is on, the timer
cadence and the disk threshold are expressions over `group_names`, and the backup
declaration the reclaim protects is a `lookup` of common.yaml. A test that read
the raw YAML would see the expression text, and `"{{ ... }}" | bool` is false, so
it would certify a role with the reclaim switched off everywhere. This resolves
each default as Ansible does -- lazily, a value at a time, as native types --
so the tests read what a host actually gets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, UndefinedError
from jinja2.nativetypes import NativeEnvironment

from tests.ansible_jinja import _to_bool

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "node_maintenance"
COMMON = REPO / "infra" / "config" / "values" / "common.yaml"


def _lookup(kind: str, path: str) -> str:
    if kind not in ("file", "ansible.builtin.file"):
        raise NotImplementedError(f"lookup {kind!r} is not modelled here")
    return Path(path).read_text(encoding="utf-8")


def _register(env: Environment) -> Environment:
    env.filters["bool"] = _to_bool
    env.filters["from_yaml"] = yaml.safe_load
    env.filters["to_nice_json"] = lambda value: json.dumps(value, indent=4, sort_keys=True)
    env.globals["lookup"] = _lookup
    return env


def resolve_defaults(group_names: list[str], hostname: str = "kubelab-test") -> dict[str, Any]:
    """Every default, rendered for a host in `group_names`.

    Resolved by repeated passes: a value whose template names a default not
    resolved yet raises under StrictUndefined and is retried next pass. A pass
    that resolves nothing while values remain means a cycle or a missing name,
    and is reported rather than looped on.
    """
    raw: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
    env = _register(NativeEnvironment(undefined=StrictUndefined))
    base = {"group_names": list(group_names), "role_path": str(ROLE), "inventory_hostname": hostname}
    resolved: dict[str, Any] = {}
    pending = dict(raw)
    while pending:
        progressed = False
        for name, value in list(pending.items()):
            if not (isinstance(value, str) and "{{" in value):
                resolved[name] = value
            else:
                try:
                    resolved[name] = env.from_string(value).render({**base, **resolved})
                except UndefinedError:
                    continue
            del pending[name]
            progressed = True
        if not progressed:
            raise AssertionError(f"defaults that never resolve: {sorted(pending)}")
    return resolved


def render_script(group_names: list[str]) -> str:
    """kubelab-maintenance.sh.j2 as this host's timer would run it."""
    env = _register(Environment(undefined=StrictUndefined))
    template = (ROLE / "templates" / "kubelab-maintenance.sh.j2").read_text(encoding="utf-8")
    context = {**resolve_defaults(group_names), "ansible_managed": "am", "inventory_hostname": "kubelab-test"}
    return env.from_string(template).render(context)


def tasks() -> list[dict[str, Any]]:
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
