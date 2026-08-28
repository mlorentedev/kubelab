"""Unit tests for multi-forge webhook payload normalization and HMAC validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
from pathlib import Path

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / "infra/n8n/workflows/multi-forge-sync.json"


def get_forge_parser_js() -> str:
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        data = json.load(f)
    node = next(n for n in data["nodes"] if n["name"] == "Parse Forge Event")
    return node["parameters"]["jsCode"]


def eval_forge_node(body: dict, headers: dict, env: dict) -> dict:
    """Execute the exact workflow JS code in Node.js."""
    js_code = get_forge_parser_js()
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


def generate_hmac_sha256(payload: bytes, secret: str) -> str:
    """Generate GitHub/Gitea style sha256 HMAC signature."""
    mac = hmac.new(secret.encode(), payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def test_workflow_node_valid_hmac_and_open_pr() -> None:
    body = {
        "action": "opened",
        "pull_request": {
            "title": "feat: IDP-035 add sync",
            "html_url": "https://github.com/org/repo/pull/1",
            "merged": False,
            "head": {"ref": "feature/idp-035-sync"},
        },
    }
    secret = "my-secret-key"
    payload_str = json.dumps(body, separators=(",", ":"))
    sig = generate_hmac_sha256(payload_str.encode(), secret)
    headers = {"x-hub-signature-256": sig}
    env = {"FORGE_WEBHOOK_SECRET": secret}

    result = eval_forge_node(body, headers, env)
    assert result["isValidSig"] is True
    assert result["hasTask"] is True
    assert result["taskKey"] == "IDP-035"
    assert result["taskId"] == 35
    assert result["targetBucket"] == "In Review"
    assert result["isDone"] is False


def test_workflow_node_raw_body_string_and_valid_hmac() -> None:
    raw_payload = '{"action":"opened","pull_request":{"title":"feat: IDP-035 add sync","html_url":"https://github.com/org/repo/pull/1","merged":false,"head":{"ref":"feature/idp-035-sync"}}}'
    secret = "my-secret-key"
    sig = generate_hmac_sha256(raw_payload.encode(), secret)
    headers = {"x-hub-signature-256": sig}
    env = {"FORGE_WEBHOOK_SECRET": secret}

    js_code = get_forge_parser_js()
    script = f"""
    const $json = {{body: {raw_payload}, rawBody: {json.dumps(raw_payload)}, headers: {json.dumps(headers)}}};
    const $env = {json.dumps(env)};
    const result = (() => {{
        {js_code}
    }})();
    console.log(JSON.stringify(result[0].json));
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    result = json.loads(proc.stdout.strip())
    assert result["isValidSig"] is True
    assert result["hasTask"] is True
    assert result["taskKey"] == "IDP-035"
    assert result["taskId"] == 35
    assert result["targetBucket"] == "In Review"


def test_workflow_node_valid_hmac_and_merged_pr() -> None:
    body = {
        "action": "closed",
        "pull_request": {
            "title": "fix: GITOPS-007 resolve sync",
            "html_url": "https://github.com/org/repo/pull/2",
            "merged": True,
            "head": {"ref": "master"},
        },
    }
    secret = "my-secret-key"
    payload_str = json.dumps(body, separators=(",", ":"))
    sig = generate_hmac_sha256(payload_str.encode(), secret)
    headers = {"x-gitea-signature": sig}
    env = {"FORGE_WEBHOOK_SECRET": secret}

    result = eval_forge_node(body, headers, env)
    assert result["isValidSig"] is True
    assert result["hasTask"] is True
    assert result["taskKey"] == "GITOPS-007"
    assert result["taskId"] == 7
    assert result["targetBucket"] == "Done"
    assert result["isDone"] is True


def test_workflow_node_invalid_hmac_fails_closed() -> None:
    body = {
        "action": "opened",
        "pull_request": {"title": "feat: IDP-035 add sync"},
    }
    secret = "my-secret-key"
    headers = {"x-hub-signature-256": "sha256=invalid"}
    env = {"FORGE_WEBHOOK_SECRET": secret}

    result = eval_forge_node(body, headers, env)
    assert result["isValidSig"] is False
    assert result["hasTask"] is False


def test_workflow_node_missing_signature_fails_closed() -> None:
    body = {
        "action": "opened",
        "pull_request": {"title": "feat: IDP-035 add sync"},
    }
    secret = "my-secret-key"
    headers = {}
    env = {"FORGE_WEBHOOK_SECRET": secret}

    result = eval_forge_node(body, headers, env)
    assert result["isValidSig"] is False
    assert result["hasTask"] is False


def test_multi_forge_workflow_json_structure() -> None:
    assert WORKFLOW_PATH.is_file()
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("name") == "multi-forge-sync"
    webhook_node = next(n for n in data["nodes"] if n["name"] == "Webhook Ingress")
    assert webhook_node["parameters"]["authentication"] == "none"

    update_node = next(n for n in data["nodes"] if n["name"] == "Update Vikunja Task State")
    assert "http://vikunja:3456/api/v1/tasks/" in update_node["parameters"]["url"]

    comment_node = next(n for n in data["nodes"] if n["name"] == "Append PR URL Comment")
    assert "/comments" in comment_node["parameters"]["url"]
