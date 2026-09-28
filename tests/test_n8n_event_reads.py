"""APP-CONFIG-016 (#1871) AC3: no node reads the event from a response.

In n8n, `$json` is the node's INPUT, which is the previous node's output. After
an HTTP Request node, that is the response: Vikunja's task, Apprise's
acknowledgement, Slack's answer. It is not the event the workflow is
processing. An expression such as `$json.taskKey` there does not fail. It
evaluates to `undefined`, the request goes out with `undefined` in its URL or
body, and the workflow reports success.

The pattern was written five times, in three workflows, and found one instance
at a time:

- `Respond Task Created` answered 201 without the task id (#1864, measured);
- `Append PR URL Comment` would have commented on `/tasks/undefined` (#1871);
  it never ran, because the extractor before it never matched;
- the `#dev-activity` notice and both `Respond 200` bodies read fields their
  input does not carry.

So this checks the class. An event field is any key that a Code node in the same
workflow returns. The key set is read from the code, not listed here, so a new
field is covered the day it is added. A node fed by an HTTP Request node must
reach those fields through `$('<node that produced them>')`, never through
`$json`. Reading the response itself through `$json` stays allowed:
`Notify Task Created` does it to name the task Vikunja created.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / "infra" / "n8n" / "workflows"

HTTP = "n8n-nodes-base.httpRequest"
CODE = "n8n-nodes-base.code"

KNOWN_BROKEN = {
    "slack-task-capture.json": "APP-CONFIG-017 (#1877) owns slack-task-capture's post-create reads",
}

_RETURN_KEY = re.compile(r"^\s*([A-Za-z_]\w*)\s*:", re.MULTILINE)
_JSON_READ = re.compile(r"\$json\.([A-Za-z_]\w*)")


def event_fields(workflow: dict[str, Any]) -> set[str]:
    """Keys the workflow's Code nodes return: every `key:` inside each node's last `return [`."""
    fields: set[str] = set()
    for node in workflow["nodes"]:
        if node["type"] != CODE:
            continue
        js = node["parameters"].get("jsCode", "")
        start = js.rfind("return [")
        if start >= 0:
            fields |= set(_RETURN_KEY.findall(js[start:])) - {"json"}
    return fields


def fed_by_http(workflow: dict[str, Any]) -> dict[str, list[str]]:
    """Node name -> the HTTP Request nodes wired directly into it."""
    types = {n["name"]: n["type"] for n in workflow["nodes"]}
    fed: dict[str, list[str]] = {}
    for source, conns in workflow["connections"].items():
        if types.get(source) != HTTP:
            continue
        for output in conns.get("main", []):
            for target in output:
                fed.setdefault(target["node"], []).append(source)
    return fed


def misreads(workflow: dict[str, Any]) -> list[str]:
    fields = event_fields(workflow)
    params = {n["name"]: json.dumps(n.get("parameters", {})) for n in workflow["nodes"]}
    found = []
    for node, sources in sorted(fed_by_http(workflow).items()):
        bad = sorted({f for f in _JSON_READ.findall(params[node]) if f in fields})
        if bad:
            found.append(f"{node} (after {', '.join(sorted(sources))}) reads $json.{{{', '.join(bad)}}}")
    return found


def _workflows() -> list[Any]:
    params = []
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        marks = [pytest.mark.xfail(strict=True, reason=KNOWN_BROKEN[path.name])] if path.name in KNOWN_BROKEN else []
        params.append(pytest.param(path, id=path.stem, marks=marks))
    return params


@pytest.mark.parametrize("path", _workflows())
def test_no_node_reads_the_event_from_a_response(path: pathlib.Path) -> None:
    found = misreads(json.loads(path.read_text(encoding="utf-8")))
    assert not found, (
        f"{path.name}: after an HTTP Request node, $json is the RESPONSE, not the event. "
        "Read the event from the node that produced it, e.g. $('Parse Forge Event').first().json:\n  "
        + "\n  ".join(found)
    )


def test_the_detector_finds_the_defect_it_exists_for() -> None:
    """The #1864 shape, rebuilt: a Code node returns `taskKey`, an HTTP node
    follows, and the next node reads `$json.taskKey`. Also checks the allowed
    case: reading the response's own `id` is not flagged."""
    workflow = {
        "nodes": [
            {"name": "Parse", "type": CODE, "parameters": {"jsCode": "return [{ json: {\n  taskKey: k,\n} }];"}},
            {"name": "Create", "type": HTTP, "parameters": {}},
            {"name": "Notify", "type": HTTP, "parameters": {"jsonBody": "={{ $json.id }} {{ $json.taskKey }}"}},
        ],
        "connections": {
            "Parse": {"main": [[{"node": "Create"}]]},
            "Create": {"main": [[{"node": "Notify"}]]},
        },
    }
    assert misreads(workflow) == ["Notify (after Create) reads $json.{taskKey}"]


def test_the_guard_sees_every_workflow() -> None:
    names = {p.name for p in WORKFLOW_DIR.glob("*.json")}
    assert {"multi-forge-sync.json", "slack-task-capture.json", "agent-dispatcher.json"} <= names
    assert set(KNOWN_BROKEN) <= names, "a KNOWN_BROKEN entry names a workflow that no longer exists"
