"""Run an n8n Code node's committed `jsCode` on the item n8n really hands it.

APP-CONFIG-015 (#1712). Each signature test used to build its own `$json` with a
`rawBody` string. n8n 2.12.3 never produces that: behind a Webhook v2 with
`rawBody: true` the bytes are in `binary.data`, and `$json.rawBody` is undefined.
The tests passed and every real signed request failed (lesson-467). So the item
here is built FROM the fixture captured in the pinned image
(`tests/fixtures/n8n/capture_webhook_item.py`), and
`tests/test_n8n_webhook_item_fixture.py` holds this module to that capture.

What the fake runtime provides, each measured by the capture rather than assumed:
- `$input`, `$json`, `$env`, and `this.helpers.getBinaryDataBuffer(i, prop)`,
  which resolves to the exact bytes sent, and REJECTS when the property is absent;
- the node body runs inside an async function, as n8n runs it, so `await` works.
"""

from __future__ import annotations

import base64
import copy
import json
import pathlib
import subprocess
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / "infra" / "n8n" / "workflows"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "n8n" / "webhook-v2-rawbody-item.json"

FIXTURE: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CAPTURED_ITEM: dict[str, Any] = FIXTURE["code_node_saw"]["item"]


def node_js(workflow: str, node_name: str) -> str:
    data = json.loads((WORKFLOW_DIR / workflow).read_text(encoding="utf-8"))
    return next(n for n in data["nodes"] if n["name"] == node_name)["parameters"]["jsCode"]


def webhook_item(
    raw: bytes | None,
    headers: dict[str, str],
    parsed_body: Any,
    content_type: str = "application/json",
) -> dict[str, Any]:
    """The item a Code node receives behind a Webhook v2 with `rawBody: true`.

    `raw=None` drops the binary property, the shape a request with no body (or a
    webhook without `rawBody`) produces. Header names are lower-cased because the
    Webhook node passes Node's `req.headers`, which are, and `content-type` is
    always present, as it is on every request the capture recorded.
    """
    item = copy.deepcopy(CAPTURED_ITEM)
    item["json"]["headers"] = {"content-type": content_type, **{k.lower(): v for k, v in headers.items()}}
    item["json"]["body"] = parsed_body
    if raw is None:
        item.pop("binary", None)
    else:
        item["binary"]["data"]["data"] = base64.b64encode(raw).decode()
        item["binary"]["data"]["mimeType"] = content_type
    return item


def run_code_node(js: str, items: list[dict[str, Any]], env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Execute `js` as an n8n Code node (run once for all items); return each output item's json."""
    script = f"""
    const ITEMS = {json.dumps(items)};
    const $input = {{ all: () => ITEMS, first: () => ITEMS[0] }};
    const $json = ITEMS[0].json;
    const $env = {json.dumps(env or {})};
    const helpers = {{
      getBinaryDataBuffer: async (itemIndex, property) => {{
        const binary = ITEMS[itemIndex] && ITEMS[itemIndex].binary && ITEMS[itemIndex].binary[property];
        if (!binary) throw {{}};  // n8n rejects with an opaque object; the capture records it
        return Buffer.from(binary.data, 'base64');
      }},
    }};
    (async function () {{
      {js}
    }}).call({{ helpers }}).then(
      (out) => console.log(JSON.stringify(out.map((i) => i.json))),
      (err) => {{ console.error(err); process.exit(1); }},
    );
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout.strip())
