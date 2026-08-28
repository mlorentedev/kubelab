"""Unit tests for Slack slash command parser and signature verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import time
from pathlib import Path

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / "infra/n8n/workflows/slack-task-capture.json"


def get_slack_parser_js() -> str:
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        data = json.load(f)
    node = next(n for n in data["nodes"] if n["name"] == "Parse Slack Command")
    return node["parameters"]["jsCode"]


def eval_slack_node(body: dict, headers: dict, env: dict) -> dict:
    """Execute the exact workflow JS code in Node.js."""
    js_code = get_slack_parser_js()
    script = f"""
    const $json = {json.dumps({"body": body, "headers": headers})};
    const $env = {json.dumps(env)};
    const result = (() => {{
        {js_code}
    }})();
    console.log(JSON.stringify(result[0].json));
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout.strip())


def generate_slack_signature(body_str: str, secret: str, timestamp: int) -> str:
    sig_base = f"v0:{timestamp}:{body_str}"
    mac = hmac.new(secret.encode(), sig_base.encode(), hashlib.sha256)
    return f"v0={mac.hexdigest()}"


def test_slack_workflow_node_valid_signature_and_command() -> None:
    body = {
        "text": "create Refactor auth layer #kubelab P1",
        "response_url": "https://hooks.slack.com/commands/123",
        "user_name": "developer",
    }
    secret = "slack-signing-secret"
    ts = int(time.time())
    body_json = json.dumps(body, separators=(",", ":"))
    sig = generate_slack_signature(body_json, secret, ts)
    headers = {
        "x-slack-signature": sig,
        "x-slack-request-timestamp": str(ts),
    }
    env = {"SLACK_SIGNING_SECRET": secret}

    result = eval_slack_node(body, headers, env)
    assert result["isValidSlack"] is True
    assert result["title"] == "Refactor auth layer"
    assert result["project"] == "kubelab"
    assert result["priority"] == "P1"
    assert result["priorityNum"] == 3


def test_slack_workflow_node_invalid_signature_fails_closed() -> None:
    body = {"text": "create Task without auth"}
    secret = "slack-signing-secret"
    ts = int(time.time())
    headers = {
        "x-slack-signature": "v0=invalid_sig",
        "x-slack-request-timestamp": str(ts),
    }
    env = {"SLACK_SIGNING_SECRET": secret}

    result = eval_slack_node(body, headers, env)
    assert result["isValidSlack"] is False
    assert "Invalid" in result["ackMessage"]


def test_slack_workflow_node_expired_timestamp_fails_closed() -> None:
    body = {"text": "create Task with expired timestamp"}
    secret = "slack-signing-secret"
    ts = int(time.time()) - 400  # > 5 minutes ago
    sig = generate_slack_signature(json.dumps(body), secret, ts)
    headers = {
        "x-slack-signature": sig,
        "x-slack-request-timestamp": str(ts),
    }
    env = {"SLACK_SIGNING_SECRET": secret}

    result = eval_slack_node(body, headers, env)
    assert result["isValidSlack"] is False


def test_slack_workflow_json_structure() -> None:
    assert WORKFLOW_PATH.is_file()
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("name") == "slack-task-capture"
    webhook_node = next(n for n in data["nodes"] if n["name"] == "Webhook Slack Ingress")
    assert webhook_node["parameters"]["authentication"] == "none"

    create_node = next(n for n in data["nodes"] if n["name"] == "Create Task in Vikunja")
    assert "http://vikunja:3456/api/v1/projects/" in create_node["parameters"]["url"]

    update_node = next(n for n in data["nodes"] if n["name"] == "Update Slack via Response URL")
    assert "responseUrl" in update_node["parameters"]["url"]
