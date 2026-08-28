"""Unit tests for Slack ChatOps task capture and signature verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path


def generate_slack_signature(body: bytes, secret: str, timestamp: int) -> str:
    """Generate Slack-compatible v0 HMAC signature."""
    sig_basestring = f"v0:{timestamp}:".encode() + body
    mac = hmac.new(secret.encode(), sig_basestring, hashlib.sha256)
    return f"v0={mac.hexdigest()}"


def verify_slack_signature(body: bytes, secret: str, signature: str, timestamp: int, max_drift_s: int = 300) -> bool:
    """Verify Slack signature with replay attack protection (5 minute timestamp window)."""
    now = int(time.time())
    if abs(now - timestamp) > max_drift_s:
        return False

    expected = generate_slack_signature(body, secret, timestamp)
    return hmac.compare_digest(expected, signature)


def parse_slack_slash_command(text: str) -> dict[str, str]:
    """Parse `/task create [title] #[project] [priority]`."""
    parts = text.strip().split()
    if not parts:
        return {"action": "help", "title": "", "project": "kubelab", "priority": "P2"}

    action = parts[0].lower()
    if action != "create":
        return {"action": action, "title": " ".join(parts[1:]), "project": "kubelab", "priority": "P2"}

    remaining = parts[1:]
    project = "kubelab"
    priority = "P2"
    title_words = []

    for word in remaining:
        if word.startswith("#"):
            project = word[1:]
        elif word.upper() in ("P0", "P1", "P2", "P3"):
            priority = word.upper()
        else:
            title_words.append(word)

    return {
        "action": "create",
        "title": " ".join(title_words),
        "project": project,
        "priority": priority,
    }


def test_slack_signature_valid() -> None:
    body = b"command=%2Ftask&text=create+scaffold+spec+%23kubelab+P1"
    secret = "slack-signing-secret-12345"
    ts = int(time.time())
    sig = generate_slack_signature(body, secret, ts)

    assert verify_slack_signature(body, secret, sig, ts) is True


def test_slack_signature_expired_timestamp_fails() -> None:
    body = b"command=%2Ftask&text=test"
    secret = "slack-signing-secret-12345"
    expired_ts = int(time.time()) - 400  # > 5 minutes ago
    sig = generate_slack_signature(body, secret, expired_ts)

    assert verify_slack_signature(body, secret, sig, expired_ts) is False


def test_parse_slack_slash_command_create_with_project_and_priority() -> None:
    cmd = parse_slack_slash_command("create Refactor auth layer #kubelab P1")
    assert cmd["action"] == "create"
    assert cmd["title"] == "Refactor auth layer"
    assert cmd["project"] == "kubelab"
    assert cmd["priority"] == "P1"


def test_parse_slack_slash_command_defaults() -> None:
    cmd = parse_slack_slash_command("create Simple task title")
    assert cmd["action"] == "create"
    assert cmd["title"] == "Simple task title"
    assert cmd["project"] == "kubelab"
    assert cmd["priority"] == "P2"


def test_slack_task_capture_workflow_json_exists_and_is_valid() -> None:
    workflow_path = Path(__file__).resolve().parent.parent / "infra/n8n/workflows/slack-task-capture.json"
    assert workflow_path.is_file(), "slack-task-capture.json must exist in infra/n8n/workflows/"

    with open(workflow_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("name") == "slack-task-capture"
    assert len(data.get("nodes", [])) >= 5
    assert "connections" in data

    # Verify Webhook Authentication
    webhook_node = next((n for n in data["nodes"] if n["name"] == "Webhook Slack Ingress"), None)
    assert webhook_node is not None
    assert webhook_node["parameters"]["authentication"] == "none"

    parse_node = next((n for n in data["nodes"] if n["name"] == "Parse Slack Command"), None)
    assert parse_node is not None
    js = parse_node["parameters"]["jsCode"]
    assert "ackMessage" in js
    assert "responseUrl" in js

    create_node = next((n for n in data["nodes"] if n["name"] == "Create Task in Vikunja"), None)
    assert create_node is not None
    assert "http://vikunja:3456/api/v1/projects/" in create_node["parameters"]["url"]

    response_node = next((n for n in data["nodes"] if n["name"] == "Update Slack via Response URL"), None)
    assert response_node is not None
    assert "responseUrl" in response_node["parameters"]["url"]
