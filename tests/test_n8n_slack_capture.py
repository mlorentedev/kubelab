"""`Parse Slack Command`: Slack request signing and command parsing (APP-CONFIG-015 AC2).

Every test feeds the node the item n8n 2.12.3 really produces behind a Webhook v2
with `rawBody: true` for a Slack slash command: the form already parsed into
`body`, and the signed bytes in `binary.data` (captured in `tests/fixtures/n8n/`).
The previous tests fed a `$json.rawBody` string n8n never produces (#1712,
lesson-467).

Slack signs `v0:<timestamp>:<raw body>`. The bodies here carry a bare `~`, as an
RFC 3986 encoder leaves it, while `URLSearchParams(...).toString()` writes `%7E`
(measured in Node), so a body rebuilt from the parsed form does not reproduce the
signed bytes. Which encoder Slack uses is not assumed; the point is that only the
delivered bytes are ever verified.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any

from tests.n8n_code_node import (
    EMPTY_ITEM,
    ERROR_ITEM,
    node_js,
    run_code_node,
    run_items_node,
    split_items,
    webhook_item,
    wrapped_array,
    wrapped_data,
)
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.n8n_import import resolve_placeholders

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / "infra/n8n/workflows/slack-task-capture.json"
SECRET = "slack-signing-secret"
FORM = "application/x-www-form-urlencoded"


def slack_form(fields: dict[str, str]) -> bytes:
    """A form body as an RFC 3986 encoder writes it: spaces as `+`, `~` left bare."""
    return urllib.parse.urlencode(fields).encode()


def slack_signature(raw: bytes, ts: int, secret: str = SECRET) -> str:
    base = f"v0:{ts}:".encode() + raw
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def parse(
    raw: bytes | None,
    fields: dict[str, str],
    headers: dict[str, str],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    js = node_js("slack-task-capture.json", "Parse Slack Command")
    item = webhook_item(raw, headers, fields, content_type=FORM)
    (out,) = run_code_node(js, [item], {"SLACK_SIGNING_SECRET": SECRET} if env is None else env)
    return out


def signed(fields: dict[str, str], ts: int | None = None) -> tuple[bytes, dict[str, str]]:
    ts = int(time.time()) if ts is None else ts
    raw = slack_form(fields)
    return raw, {"X-Slack-Signature": slack_signature(raw, ts), "X-Slack-Request-Timestamp": str(ts)}


COMMAND = {
    "command": "/task",
    "text": "create Production fix ~now #teledyne P0",
    "response_url": "https://hooks.slack.com/commands/123",
    "user_name": "admin",
}


def test_signature_over_the_delivered_form_bytes_is_valid() -> None:
    raw, headers = signed(COMMAND)
    result = parse(raw, COMMAND, headers)
    assert result["isValidSlack"] is True
    assert result["title"] == "Production fix ~now"
    assert result["project"] == "teledyne"
    assert result["priority"] == "P0"
    assert result["priorityNum"] == 4


def test_command_without_project_or_priority_parses() -> None:
    fields = {**COMMAND, "text": "create Refactor auth layer #kubelab P1"}
    raw, headers = signed(fields)
    result = parse(raw, fields, headers)
    assert result["isValidSlack"] is True
    assert result["title"] == "Refactor auth layer"
    assert result["project"] == "kubelab"
    assert result["priority"] == "P1"
    assert result["priorityNum"] == 3


def test_wrong_signature_fails_closed() -> None:
    raw, headers = signed(COMMAND)
    headers["X-Slack-Signature"] = slack_signature(raw, int(headers["X-Slack-Request-Timestamp"]), "other")
    result = parse(raw, COMMAND, headers)
    assert result["isValidSlack"] is False
    assert "Invalid" in result["ackMessage"]


def test_stale_timestamp_fails_closed_even_when_correctly_signed() -> None:
    raw, headers = signed(COMMAND, ts=int(time.time()) - 400)  # outside Slack's 5-minute window
    result = parse(raw, COMMAND, headers)
    assert result["isValidSlack"] is False


def test_signature_over_different_bytes_fails_closed() -> None:
    raw, headers = signed(COMMAND)
    tampered = slack_form({**COMMAND, "text": "create Something else #kubelab P0"})
    result = parse(tampered, COMMAND, headers)
    assert result["isValidSlack"] is False


def test_no_raw_bytes_fails_closed_even_when_the_rebuilt_form_would_match() -> None:
    """Without the signed bytes nothing is trusted: the old re-encoding fallback must not return.

    The signature is computed over exactly what `new URLSearchParams(body).toString()`
    produces, which is what the removed fallback verified.
    """
    ts = int(time.time())
    # `URLSearchParams` differs from Python's encoder only on `~` for this command.
    rebuilt = urllib.parse.urlencode(COMMAND).replace("~", "%7E").encode()
    headers = {"X-Slack-Signature": slack_signature(rebuilt, ts), "X-Slack-Request-Timestamp": str(ts)}
    result = parse(None, COMMAND, headers)
    assert result["isValidSlack"] is False


def test_missing_secret_fails_closed() -> None:
    raw, headers = signed(COMMAND)
    result = parse(raw, COMMAND, headers, env={})
    assert result["isValidSlack"] is False


def test_slack_workflow_json_structure() -> None:
    assert WORKFLOW_PATH.is_file()
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("name") == "slack-task-capture"
    webhook_node = next(n for n in data["nodes"] if n["name"] == "Webhook Slack Ingress")
    assert webhook_node["parameters"]["authentication"] == "none"
    assert webhook_node["parameters"]["options"]["rawBody"] is True

    create_node = next(n for n in data["nodes"] if n["name"] == "Create Task in Vikunja")
    assert "http://vikunja:3456/api/v1/projects/" in create_node["parameters"]["url"]

    update_node = next(n for n in data["nodes"] if n["name"] == "Update Slack via Response URL")
    assert "responseUrl" in update_node["parameters"]["url"]


# --- APP-CONFIG-017 (#1877): project resolution and the post-create reads -----------------------

PROJECTS = [{"id": 7, "title": "Inbox"}, {"id": 12, "title": "Kubelab", "identifier": "KUBE"}]
COMMAND_OUT = {
    "title": "Fix the thing",
    "project": "kubelab",
    "priority": "P2",
    "priorityNum": 2,
    "responseUrl": "https://hooks.slack.test/response/1",
    "userName": "manu",
}


def extract(items: list[Any], command: dict[str, Any] | None = None) -> dict[str, Any]:
    return run_items_node(
        node_js("slack-task-capture.json", "Extract Project ID"),
        items,
        {"Parse Slack Command": COMMAND_OUT if command is None else command},
    )


def workflow() -> dict[str, Any]:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def node(name: str) -> dict[str, Any]:
    return next(n for n in workflow()["nodes"] if n["name"] == name)


def test_the_project_is_found_in_every_shape_the_lookup_can_arrive_in() -> None:
    """`GET /projects` returns an array, which n8n emits as one item per element.

    Reading `$json` saw only the first project, so the match always failed and the
    task went to project 1 whatever the command named."""
    for shape in (split_items, wrapped_array, wrapped_data):
        out = extract(shape(PROJECTS))
        assert out["projectFound"] is True, shape.__name__
        assert out["projectId"] == 12, shape.__name__


def test_the_project_can_be_named_by_its_identifier() -> None:
    out = extract(split_items(PROJECTS), {**COMMAND_OUT, "project": "kube"})
    assert out["projectId"] == 12


def test_an_unknown_project_fails_closed_instead_of_defaulting_to_project_1() -> None:
    for items in (split_items(PROJECTS), EMPTY_ITEM, ERROR_ITEM):
        out = extract(items, {**COMMAND_OUT, "project": "nonexistent"})
        assert out["projectFound"] is False
        assert out.get("projectId") is None
        assert "nonexistent" in out["errorMessage"]


def test_a_failed_lookup_says_so_rather_than_naming_the_project_unknown() -> None:
    out = extract(ERROR_ITEM)
    assert out["projectFound"] is False
    assert "could not" in out["errorMessage"].lower()


def test_the_unknown_project_branch_answers_slack_and_never_creates() -> None:
    data = workflow()
    gate = data["connections"]["Extract Project ID"]["main"][0]
    assert [t["node"] for t in gate] == ["Project Found?"]
    found, missing = data["connections"]["Project Found?"]["main"]
    assert [t["node"] for t in found] == ["Create Task in Vikunja"]
    assert [t["node"] for t in missing] == ["Tell Slack the Project Is Unknown"]
    tell = node("Tell Slack the Project Is Unknown")["parameters"]
    assert "$('Extract Project ID')" in tell["url"] and "responseUrl" in tell["url"]
    assert "errorMessage" in tell["jsonBody"]
    assert "Tell Slack the Project Is Unknown" not in data["connections"], "the error branch must end there"


def test_the_nodes_after_the_create_read_the_command_not_the_response() -> None:
    update = json.dumps(node("Update Slack via Response URL")["parameters"])
    notify = json.dumps(node("Notify #dev-activity")["parameters"])
    for params in (update, notify):
        assert "$('Extract Project ID')" in params
    for field in ("responseUrl", "userName", "project", "priority"):
        assert f"$json.{field}" not in update + notify, field


def test_error_handling_sits_where_n8n_reads_it() -> None:
    for name in ("Lookup Vikunja Projects", "Create Task in Vikunja", "Update Slack via Response URL"):
        assert "continueOnFail" not in node(name)["parameters"].get("options", {}), name
    # The lookup's failure must reach `Extract Project ID`, which turns it into an answer.
    assert node("Lookup Vikunja Projects")["onError"] == "continueRegularOutput"
    # A failed create must reach `Task Created?`, which answers Slack (#2312): halting is silent,
    # because Slack was acknowledged before the pipeline ran.
    assert node("Create Task in Vikunja")["onError"] == "continueRegularOutput"
    # The task already exists by then; a failed confirmation must not stop the dev-activity notice.
    assert node("Update Slack via Response URL")["onError"] == "continueRegularOutput"


def test_an_empty_project_list_still_reaches_the_answer_node() -> None:
    # A 200 `[]` makes the HTTP node emit zero items, and a Code node given none never runs,
    # so the run would end with nothing posted to response_url. alwaysOutputData turns that
    # into one empty item, which `Extract Project ID` answers as "no such project".
    assert node("Lookup Vikunja Projects")["alwaysOutputData"] is True


def test_a_command_without_a_project_targets_the_declared_default_that_the_lookup_can_find() -> None:
    # `Extract Project ID` fails closed, so the parse default must be a real project title, not
    # a name nobody created. It is the same SSOT value multi-forge-sync resolves.
    fields = {**COMMAND, "text": "create Refactor auth layer P1"}
    raw, headers = signed(fields)
    js = resolve_placeholders(
        node_js("slack-task-capture.json", "Parse Slack Command"), ConfigurationManager(env="prod")
    )
    item = webhook_item(raw, headers, fields, content_type=FORM)
    (out,) = run_code_node(js, [item], {"SLACK_SIGNING_SECRET": SECRET})
    assert out["project"] == "Bitacora"

    extract = node_js("slack-task-capture.json", "Extract Project ID")
    found = run_items_node(extract, [{"id": 7, "title": "Bitacora"}], {"Parse Slack Command": out})
    assert found["projectFound"] is True


def _task_created(item: dict[str, Any]) -> bool:
    """Evaluate `Task Created?`'s condition on one item, as n8n would."""
    expression = node("Task Created?")["parameters"]["conditions"]["conditions"][0]["leftValue"]
    assert expression.startswith("={{") and expression.endswith("}}")
    script = f"const $json = {json.dumps(item)}; console.log(JSON.stringify({expression[3:-2]}));"
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_a_failed_create_is_told_to_slack_instead_of_ending_silently() -> None:
    assert _task_created({"id": 14, "title": "x", "project_id": 4}) is True
    assert _task_created(ERROR_ITEM[0]) is False
    assert _task_created({}) is False, "a 200 that carries no task is not a created task"


def test_the_create_failure_branch_answers_slack_and_stops_before_the_success_nodes() -> None:
    data = workflow()
    assert [t["node"] for t in data["connections"]["Create Task in Vikunja"]["main"][0]] == ["Task Created?"]
    created, failed = data["connections"]["Task Created?"]["main"]
    assert [t["node"] for t in created] == ["Update Slack via Response URL"]
    assert [t["node"] for t in failed] == ["Tell Slack the Create Failed"]
    tell = node("Tell Slack the Create Failed")["parameters"]
    assert "$('Extract Project ID')" in tell["url"] and "responseUrl" in tell["url"]
    assert "nothing was created" in tell["jsonBody"]
    assert "Tell Slack the Create Failed" not in data["connections"], "the failure branch must end there"
    for name in ("Update Slack via Response URL", "Notify #dev-activity"):
        assert name not in [t["node"] for t in failed], f"{name} announces a task that does not exist"
