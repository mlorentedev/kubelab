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
import time
import urllib.parse
from pathlib import Path
from typing import Any

from tests.n8n_code_node import node_js, run_code_node, webhook_item

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
