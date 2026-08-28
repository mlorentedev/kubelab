"""Unit tests for multi-forge webhook payload normalization and HMAC validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path


def generate_hmac_sha256(payload: bytes, secret: str) -> str:
    """Generate GitHub/Gitea style sha256 HMAC signature."""
    mac = hmac.new(secret.encode(), payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_hmac(payload: bytes, secret: str, signature: str) -> bool:
    """Verify HMAC signature securely with constant-time comparison."""
    if not signature.startswith("sha256="):
        return False
    expected = generate_hmac_sha256(payload, secret)
    return hmac.compare_digest(expected, signature)


def extract_task_key(text: str) -> str | None:
    """Extract standard task key (e.g. IDP-035, GITOPS-003, AREA-123) from branch/title."""
    m = re.search(r"\b([A-Z]{2,10}-\d+)\b", text)
    return m.group(1) if m else None


def resolve_task_transition(event_action: str, is_merged: bool, current_state: str) -> str:
    """Monotonic state machine: Done is terminal, ignore out-of-order opens."""
    if current_state == "Done":
        return "Done"

    if event_action == "closed" and is_merged:
        return "Done"
    elif event_action in ("opened", "synchronize", "reopened"):
        return "In Review"

    return current_state


def test_hmac_verification_valid_signature() -> None:
    payload = b'{"action": "opened", "pull_request": {"title": "feat: IDP-035 add sync"}}'
    secret = "super-secret-webhook-key"
    sig = generate_hmac_sha256(payload, secret)

    assert verify_hmac(payload, secret, sig) is True


def test_hmac_verification_invalid_signature() -> None:
    payload = b'{"action": "opened"}'
    secret = "super-secret-webhook-key"
    assert verify_hmac(payload, secret, "sha256=invalid123456") is False
    assert verify_hmac(payload, secret, "invalid_prefix") is False


def test_extract_task_key_from_branch_and_title() -> None:
    assert extract_task_key("feat/idp-035-vikunja-task-platform".upper()) == "IDP-035"
    assert extract_task_key("fix(auth): AUTH-004 resolve oidc callback") == "AUTH-004"
    assert extract_task_key("chore: standard cleanup without key") is None


def test_monotonic_state_transition() -> None:
    # Open PR moves to In Review
    assert resolve_task_transition(event_action="opened", is_merged=False, current_state="In Progress") == "In Review"

    # Merged PR moves to Done
    assert resolve_task_transition(event_action="closed", is_merged=True, current_state="In Review") == "Done"

    # Late arrival of 'opened' event when task is already Done is ignored (monotonic)
    assert resolve_task_transition(event_action="opened", is_merged=False, current_state="Done") == "Done"


def test_multi_forge_workflow_json_exists_and_is_valid_n8n() -> None:
    workflow_path = Path(__file__).resolve().parent.parent / "infra/n8n/workflows/multi-forge-sync.json"
    assert workflow_path.is_file(), "multi-forge-sync.json workflow must exist in infra/n8n/workflows/"

    with open(workflow_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("name") == "multi-forge-sync"
    assert len(data.get("nodes", [])) >= 4
    assert "connections" in data

    # Verify semantic logic embedded in Parse Forge Event node
    parse_node = next((n for n in data["nodes"] if n["name"] == "Parse Forge Event"), None)
    assert parse_node is not None, "Parse Forge Event node must exist"
    js = parse_node["parameters"]["jsCode"]
    assert "targetBucket = 'Done'" in js
    assert "targetBucket = 'In Review'" in js
    assert "([A-Z]{2,10}-\\d+)" in js
