"""pre-commit's node hooks run on a pinned Node, and Renovate can see the pin (#3070).

Without a pin, nodeenv takes the latest release from the Node index each time a
hook environment is created, so a new worktree's hooks depend on what was
published that day. A `27.0.0-alpha` in the index broke every new worktree on
2026-11-03.
"""

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
RENOVATE = REPO_ROOT / "renovate.json"

EXACT = re.compile(r"^\d+\.\d+\.\d+$")


def _node_pin() -> str:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    return str(config["default_language_version"]["node"])


def _node_manager() -> dict:
    managers = json.loads(RENOVATE.read_text(encoding="utf-8"))["customManagers"]
    matches = [m for m in managers if m.get("datasourceTemplate") == "node-version"]
    assert len(matches) == 1, "exactly one Renovate manager tracks the pre-commit Node pin"
    return matches[0]


def test_node_is_pinned_to_an_exact_version():
    pin = _node_pin()
    assert EXACT.match(pin), f"node must be an exact version, not {pin!r}"


def test_renovate_manager_reads_the_pin():
    manager = _node_manager()
    assert manager["managerFilePatterns"] == ["/^\\.pre-commit-config\\.yaml$/"]
    found = [
        m.group("currentValue")
        for pattern in manager["matchStrings"]
        # Renovate uses RE2's `(?<name>)`; Python needs `(?P<name>)`.
        for m in re.finditer(
            re.sub(r"\(\?<([a-zA-Z]\w*)>", r"(?P<\1>", pattern), PRE_COMMIT.read_text(encoding="utf-8")
        )
    ]
    assert found == [_node_pin()]


def test_renovate_runs_custom_managers():
    # renovate.json declares an explicit allow-list, so a custom manager only runs
    # while `custom.regex` is on it.
    enabled = json.loads(RENOVATE.read_text(encoding="utf-8"))["enabledManagers"]
    assert "custom.regex" in enabled
