"""`Parse Forge Event`: HMAC validation and payload normalisation (APP-CONFIG-015 AC1).

Every test feeds the node the item n8n 2.12.3 really produces behind a Webhook v2
with `rawBody: true` -- the parsed `body`, and the signed bytes in `binary.data` --
built from the capture in `tests/fixtures/n8n/`. The previous tests fed a
`$json.rawBody` string n8n never produces, so they passed while every real signed
request failed its HMAC (#1712, lesson-467).

The payloads are pretty-printed and carry non-ASCII text, the way Gitea sends
them: those are exactly the two ways a body re-serialised from the parsed object
stops matching the bytes that were signed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from tests.n8n_code_node import WORKFLOW_DIR, node_js, run_code_node, webhook_item

WORKFLOW_PATH = WORKFLOW_DIR / "multi-forge-sync.json"
SECRET = "my-secret-key"
ENV = {"FORGE_WEBHOOK_SECRET": SECRET}


def gitea_bytes(body: dict[str, Any]) -> bytes:
    """What Gitea puts on the wire: indented JSON, non-ASCII left as UTF-8."""
    return json.dumps(body, indent=2, ensure_ascii=False).encode()


def hex_hmac(raw: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def parse(raw: bytes | None, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    js = node_js("multi-forge-sync.json", "Parse Forge Event")
    (out,) = run_code_node(js, [webhook_item(raw, headers, body)], ENV)
    return out


def open_pr(title: str = "feat: IDP-035 añadir sincronización 🚀") -> dict[str, Any]:
    return {
        "action": "opened",
        "pull_request": {
            "title": title,
            "html_url": "https://github.com/org/repo/pull/1",
            "merged": False,
            "head": {"ref": "feature/idp-035-sync"},
        },
    }


def test_gitea_signature_over_the_delivered_bytes_is_valid() -> None:
    """Gitea sends `X-Gitea-Signature` as bare hex over the exact body bytes."""
    body = open_pr()
    raw = gitea_bytes(body)
    result = parse(raw, {"X-Gitea-Signature": hex_hmac(raw)}, body)
    assert result["isValidSig"] is True
    assert result["hasTask"] is True
    assert result["taskKey"] == "IDP-035"
    assert result["taskId"] == 35
    assert result["targetBucket"] == "In Review"
    assert result["isDone"] is False


def test_github_prefixed_signature_over_the_delivered_bytes_is_valid() -> None:
    body = open_pr("feat: IDP-035 add sync")
    raw = json.dumps(body, separators=(",", ":")).encode()
    result = parse(raw, {"X-Hub-Signature-256": "sha256=" + hex_hmac(raw)}, body)
    assert result["isValidSig"] is True
    assert result["hasTask"] is True


def test_merged_pr_goes_to_done() -> None:
    body = {
        "action": "closed",
        "pull_request": {
            "title": "fix: GITOPS-007 resolve sync",
            "html_url": "https://github.com/org/repo/pull/2",
            "merged": True,
            "head": {"ref": "master"},
        },
    }
    raw = gitea_bytes(body)
    result = parse(raw, {"X-Gitea-Signature": hex_hmac(raw)}, body)
    assert result["isValidSig"] is True
    assert result["taskKey"] == "GITOPS-007"
    assert result["targetBucket"] == "Done"
    assert result["isDone"] is True


def test_signed_issue_opened_is_a_create_candidate() -> None:
    """#1712's own symptom: a correctly signed `opened` issue must be creatable."""
    body = {
        "action": "opened",
        "issue": {"number": 2, "title": "APP-CONFIG-008: probe", "html_url": "https://forge/i/2"},
        "repository": {"name": "openkm-brain", "owner": {"login": "teledyne"}},
    }
    raw = gitea_bytes(body)
    result = parse(raw, {"X-Gitea-Signature": hex_hmac(raw)}, body)
    assert result["isValidSig"] is True
    assert result["isIssueEvent"] is True
    assert result["isCreateCandidate"] is True


def test_wrong_signature_fails_closed() -> None:
    body = open_pr()
    raw = gitea_bytes(body)
    result = parse(raw, {"X-Gitea-Signature": hex_hmac(raw, "another-secret")}, body)
    assert result["isValidSig"] is False
    assert result["hasTask"] is False
    assert result["isCreateCandidate"] is False


def test_missing_signature_fails_closed() -> None:
    body = open_pr()
    result = parse(gitea_bytes(body), {}, body)
    assert result["isValidSig"] is False
    assert result["hasTask"] is False


def test_signature_over_different_bytes_fails_closed() -> None:
    """A body altered after signing: the signature is real, just not for these bytes."""
    body = open_pr()
    signed = gitea_bytes(body)
    tampered = gitea_bytes({**body, "action": "closed"})
    result = parse(tampered, {"X-Gitea-Signature": hex_hmac(signed)}, body)
    assert result["isValidSig"] is False


def test_no_raw_bytes_fails_closed_even_when_the_parsed_body_would_match() -> None:
    """Without the signed bytes there is nothing to verify, so nothing is trusted.

    The node used to fall back to `JSON.stringify(body)`. That fallback is the
    #1712 failure for real forges, and a signature checked over it vouches for
    bytes that were never delivered, so it must not come back: the signature here
    is computed over exactly what `JSON.stringify` of the parsed body produces.
    """
    body = open_pr("feat: IDP-035 add sync")
    js_serialisation = json.dumps(body, separators=(",", ":")).encode()
    result = parse(None, {"X-Gitea-Signature": hex_hmac(js_serialisation)}, body)
    assert result["isValidSig"] is False
    assert result["hasTask"] is False


def test_missing_secret_fails_closed() -> None:
    body = open_pr()
    raw = gitea_bytes(body)
    js = node_js("multi-forge-sync.json", "Parse Forge Event")
    (result,) = run_code_node(js, [webhook_item(raw, {"X-Gitea-Signature": hex_hmac(raw, "")}, body)], {})
    assert result["isValidSig"] is False


def test_multi_forge_workflow_json_structure() -> None:
    data = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert data.get("name") == "multi-forge-sync"
    webhook_node = next(n for n in data["nodes"] if n["name"] == "Webhook Ingress")
    assert webhook_node["parameters"]["authentication"] == "none"
    assert webhook_node["parameters"]["options"]["rawBody"] is True

    update_node = next(n for n in data["nodes"] if n["name"] == "Update Vikunja Task State")
    assert "http://vikunja:3456/api/v1/tasks/" in update_node["parameters"]["url"]

    comment_node = next(n for n in data["nodes"] if n["name"] == "Append PR URL Comment")
    assert "/comments" in comment_node["parameters"]["url"]
