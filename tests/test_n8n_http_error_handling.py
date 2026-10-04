"""APP-CONFIG-016 (#1871) AC4: an HTTP node's error handling lives where n8n reads it.

Every Vikunja, Apprise and Slack call in these workflows once carried
`parameters.options.continueOnFail: true`. n8n 2.12.3 never reads it there. The
HTTP Request node asks `this.continueOnFail()`, and that method
(n8n-core `base-execute-context.js`) returns the node-level `onError` or, when
that is unset, the node-level `continueOnFail`. An option of the same name
under `parameters` is ignored. It exists in no version of the node's
description, and the editor drops it on the next save.

So the option did the opposite of what it said, in both directions:

- a search declared to survive a 401 halted the execution instead, and the
  `searchFailed` branch its code node was written for never ran;
- a write declared to swallow its failure did fail loudly. That was the right
  behaviour, but only by accident, and the next person to "fix" the option at
  node level would have made the write silent.

The intent is written where n8n reads it, one node at a time. This guard keeps
the dead spelling from coming back. `slack-task-capture` carries the same
defect and is its own ticket, hence its strict `xfail`: fixing it turns this
red until the marker goes.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / "infra" / "n8n" / "workflows"

#: Workflows known to still carry the defect, each with the ticket that owns it.
KNOWN_BROKEN = {
    "slack-task-capture.json": "APP-CONFIG-017 (#1877) owns slack-task-capture's HTTP error handling",
}


def _workflows() -> list[Any]:
    params = []
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        marks = [pytest.mark.xfail(strict=True, reason=KNOWN_BROKEN[path.name])] if path.name in KNOWN_BROKEN else []
        params.append(pytest.param(path, id=path.stem, marks=marks))
    return params


def _http_nodes(path: pathlib.Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [n for n in data["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]


@pytest.mark.parametrize("path", _workflows())
def test_no_http_node_declares_error_handling_where_n8n_never_reads_it(path: pathlib.Path) -> None:
    dead = [
        n["name"]
        for n in _http_nodes(path)
        if isinstance(n.get("parameters", {}).get("options"), dict) and "continueOnFail" in n["parameters"]["options"]
    ]
    assert not dead, (
        f"{path.name}: `parameters.options.continueOnFail` is ignored by n8n 2.12.3 on {dead}. "
        "Say what the node should do on failure with the node-level `onError` "
        "('continueRegularOutput' for a read whose next node branches on `error`), or say nothing, "
        "so the failure halts the run"
    )


def test_the_guard_sees_every_workflow() -> None:
    """A guard parametrized over an empty glob passes by running nothing."""
    names = {p.name for p in WORKFLOW_DIR.glob("*.json")}
    assert {"multi-forge-sync.json", "slack-task-capture.json"} <= names
    assert set(KNOWN_BROKEN) <= names, "a KNOWN_BROKEN entry names a workflow that no longer exists"
