"""A Jinja environment that renders Ansible templates the way Ansible does.

Ansible ships filters that vanilla Jinja2 does not have, and `bool` is the one that
matters for a `{% if %}` gate. Without it a test either fails to render — which is
what happened, loudly and harmlessly — or, worse, the template gets rewritten to drop
the filter so the test passes.

Dropping it would be a real defect rather than a style change. Ansible passes a var
declared as `"{{ config...enabled }}"` through templating, and the result can arrive
as the STRING `"False"`. Every non-empty string is truthy in Jinja, so
`{% if act_runner_enabled %}` would render the service while the declaration says it
is disabled — the gate silently inverted for exactly the value it exists to catch.

So the template keeps `| bool` because Ansible needs it, and the tests learn the
filter because they must render what Ansible renders.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jinja2 import Environment, FileSystemLoader
from packaging.version import Version


def _to_bool(value: Any) -> bool:
    """Ansible's `bool` filter, for the cases a compose gate can produce.

    Ansible's own implementation is broader; this covers the string and native forms
    a `{% if %}` in these templates can receive, and treats anything unrecognised as
    false — the safe direction for a gate, since it withholds a service rather than
    rendering one that was not asked for.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "on", "1"}
    return bool(value)


def _regex_replace(value: str, pattern: str, replacement: str = "") -> str:
    return re.sub(pattern, replacement, value)


def _version(value: Any, version: str, operator: str = "eq") -> bool:
    """Ansible's `version` test, for the dotted numeric versions the roles compare."""
    ops = {"<": "lt", "<=": "le", "==": "eq", "!=": "ne", ">=": "ge", ">": "gt"}
    return getattr(Version(str(value)), f"__{ops.get(operator, operator)}__")(Version(version))


def ansible_env(templates_dir: str, **kwargs: Any) -> Environment:
    """A `FileSystemLoader` environment with the Ansible filters these templates use."""
    env = Environment(loader=FileSystemLoader(templates_dir), **kwargs)
    env.filters["bool"] = _to_bool
    # Jinja's own `tojson` HTML-escapes; Ansible's `to_json` is plain json.dumps.
    env.filters["to_json"] = json.dumps
    env.filters["regex_replace"] = _regex_replace
    env.tests["version"] = _version
    return env
