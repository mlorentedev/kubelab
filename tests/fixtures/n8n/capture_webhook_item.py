#!/usr/bin/env python3
"""Capture the item a Code node receives from a Webhook v2 node with `rawBody: true`.

APP-CONFIG-015 (#1712). The signature nodes' tests used to feed `$json.rawBody`,
a shape n8n never produces: n8n 2.12.3's Webhook v2 puts the raw bytes in
`binary.data` and leaves `$json.rawBody` undefined. So the tests passed while every
real signed request failed its HMAC (lesson-467). The shape is therefore captured
from the pinned image, never written by hand.

What this does, all in a throwaway container of the n8n image pinned in
`infra/k8s/base/kustomization.yaml`, with the base `n8n.env` so the Code-node
runtime flags match prod:

1. imports and publishes a probe workflow: Webhook v2 (`rawBody: true`, responds
   with the last node) -> Code node v2, the same versions as the signature nodes;
2. POSTs a pretty-printed JSON body carrying a non-ASCII character, because both
   the formatting and the UTF-8 bytes are what a re-serialised body gets wrong;
3. writes what the Code node saw -- the item, and the bytes
   `this.helpers.getBinaryDataBuffer(0, 'data')` returned, and what the same
   call does for a property that is absent -- to
   `webhook-v2-rawbody-item.json` beside this file.

Run it again after bumping n8n; `tests/test_n8n_webhook_item_fixture.py` fails
until you do.

Usage: poetry run python tests/fixtures/n8n/capture_webhook_item.py
"""

from __future__ import annotations

import base64
import json
import pathlib
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
OUTPUT = HERE / "webhook-v2-rawbody-item.json"
KUSTOMIZATION = REPO_ROOT / "infra" / "k8s" / "base" / "kustomization.yaml"
N8N_ENV = REPO_ROOT / "infra" / "k8s" / "base" / "services" / "n8n-config" / "n8n.env"
PROBE_PATH = "capture-probe"
PORT = 5699

# Pretty-printed with two-space indent, the way Gitea sends it, plus a non-ASCII
# character. A body re-serialised from the parsed object differs on both counts.
PROBE_BODY = (
    json.dumps(
        {
            "action": "opened",
            "issue": {"number": 2, "title": "APP-CONFIG-015: probe — número"},
            "repository": {"name": "probe", "owner": {"login": "kubelab"}},
        },
        indent=2,
        ensure_ascii=False,
    )
    + "\n"
).encode()

CODE = """
const item = $input.first();
const raw = await this.helpers.getBinaryDataBuffer(0, 'data');
let missingPropertyError = null;
try {
  await this.helpers.getBinaryDataBuffer(0, 'absent');
} catch (e) {
  missingPropertyError = { rejected: true, value: JSON.parse(JSON.stringify(e ?? null)) };
}
return [{ json: {
  missingPropertyError,
  item: { json: item.json, binary: item.binary },
  helperBytesBase64: raw.toString('base64'),
  rawBodyType: typeof item.json.rawBody,
  bufferAvailable: typeof Buffer !== 'undefined',
}}];
"""


def pinned_image() -> str:
    text = KUSTOMIZATION.read_text()
    tag = re.search(r"name: n8nio/n8n\s*\n\s*newTag: (\S+)", text)
    assert tag, f"no n8nio/n8n newTag in {KUSTOMIZATION}"
    return f"n8nio/n8n:{tag.group(1)}"


def probe_workflow() -> dict:
    return {
        "id": "captureProbe00001",
        "name": "capture-webhook-item",
        "active": False,
        "settings": {},
        "connections": {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}},
        "nodes": [
            {
                "id": "a0000000-0000-4000-8000-000000000001",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 0],
                "webhookId": "a0000000-0000-4000-8000-0000000000aa",
                "parameters": {
                    "httpMethod": "POST",
                    "path": PROBE_PATH,
                    "authentication": "none",
                    "responseMode": "lastNode",
                    "options": {"rawBody": True},
                },
            },
            {
                "id": "a0000000-0000-4000-8000-000000000002",
                "name": "Code",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [200, 0],
                "parameters": {"jsCode": CODE},
            },
        ],
    }


def main() -> None:
    image = pinned_image()
    with tempfile.TemporaryDirectory() as tmp:
        probe = pathlib.Path(tmp) / "probe.json"
        probe.write_text(json.dumps(probe_workflow()))
        probe.chmod(0o644)
        pathlib.Path(tmp).chmod(0o755)
        wf_id = probe_workflow()["id"]
        container = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--env-file",
                str(N8N_ENV),
                # Local capture: no proxy in front, and nothing here is reachable
                # from outside the host.
                "-e",
                "N8N_PROXY_HOPS=0",
                "-e",
                "N8N_SECURE_COOKIE=false",
                "-p",
                f"127.0.0.1:{PORT}:5678",
                "-v",
                f"{probe}:/probe.json:ro",
                "--entrypoint",
                "sh",
                image,
                "-c",
                f"n8n import:workflow --input=/probe.json && n8n publish:workflow --id={wf_id} && exec n8n start",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        try:
            response = post_when_ready(f"http://127.0.0.1:{PORT}/webhook/{PROBE_PATH}")
        except Exception:
            print(subprocess.run(["docker", "logs", container], capture_output=True, text=True).stdout[-3000:])
            raise
        finally:
            subprocess.run(["docker", "stop", container], capture_output=True, check=False)

    helper_bytes = base64.b64decode(response["helperBytesBase64"])
    assert helper_bytes == PROBE_BODY, "getBinaryDataBuffer did not return the bytes that were sent"
    fixture = {
        "_comment": "Generated by capture_webhook_item.py from the pinned n8n image. Do not edit by hand.",
        "n8n_image": image,
        "sent_body_base64": base64.b64encode(PROBE_BODY).decode(),
        "code_node_saw": response,
    }
    OUTPUT.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} from {image}")


def post_when_ready(url: str, timeout_s: int = 120) -> dict:
    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            url,
            data=PROBE_BODY,
            method="POST",
            headers={"Content-Type": "application/json", "X-Gitea-Event": "issues"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, ConnectionError) as exc:
            last = exc
            time.sleep(2)
    raise TimeoutError(f"n8n never served {url}: {last}")


if __name__ == "__main__":
    main()
