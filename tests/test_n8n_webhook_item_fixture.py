"""APP-CONFIG-015 (#1712): the Code-node test harness matches what n8n really produced.

`tests/n8n_code_node.py` builds every signature test's input from a fixture
captured in the pinned n8n image. These tests fail when the fixture is older
than the pinned image, or when the harness's item drifts from the captured one.
Re-capture with `poetry run python tests/fixtures/n8n/capture_webhook_item.py`.
"""

from __future__ import annotations

import base64
import re

from tests.n8n_code_node import CAPTURED_ITEM, FIXTURE, REPO_ROOT, run_code_node, webhook_item

KUSTOMIZATION = REPO_ROOT / "infra" / "k8s" / "base" / "kustomization.yaml"


def test_fixture_was_captured_from_the_pinned_n8n_image() -> None:
    tag = re.search(r"name: n8nio/n8n\s*\n\s*newTag: (\S+)", KUSTOMIZATION.read_text())
    assert tag
    assert FIXTURE["n8n_image"] == f"n8nio/n8n:{tag.group(1)}", (
        "n8n was bumped but the Webhook item fixture was not re-captured. Run "
        "`poetry run python tests/fixtures/n8n/capture_webhook_item.py` and commit the result."
    )


def test_n8n_delivers_the_raw_body_as_binary_and_never_as_json_rawbody() -> None:
    saw = FIXTURE["code_node_saw"]
    assert saw["rawBodyType"] == "undefined"
    assert saw["bufferAvailable"] is True
    sent = base64.b64decode(FIXTURE["sent_body_base64"])
    assert base64.b64decode(saw["helperBytesBase64"]) == sent
    assert base64.b64decode(CAPTURED_ITEM["binary"]["data"]["data"]) == sent


def test_n8n_rejects_a_binary_read_for_an_absent_property() -> None:
    assert FIXTURE["code_node_saw"]["missingPropertyError"]["rejected"] is True


def test_the_harness_item_has_the_captured_shape() -> None:
    raw = b'{\n  "a": 1\n}\n'
    item = webhook_item(raw, {"X-Test": "1"}, {"a": 1})
    assert set(item) == set(CAPTURED_ITEM)
    assert set(item["json"]) == set(CAPTURED_ITEM["json"])
    assert set(item["binary"]["data"]) == set(CAPTURED_ITEM["binary"]["data"])


def test_the_harness_runtime_behaves_as_the_capture_measured() -> None:
    """The fake `getBinaryDataBuffer` returns exact bytes and rejects on absence, like n8n's."""
    js = """
    const bytes = await this.helpers.getBinaryDataBuffer(0, 'data');
    let rejected = false;
    let thrown;
    try { await this.helpers.getBinaryDataBuffer(0, 'absent'); } catch (e) {
      rejected = true;
      thrown = {
        value: JSON.parse(JSON.stringify(e ?? null)),
        isError: e instanceof Error,
        name: e && e.name !== undefined ? String(e.name) : null,
        message: e && e.message !== undefined ? String(e.message) : null,
      };
    }
    return [{ json: { b64: bytes.toString('base64'), rawBodyType: typeof $json.rawBody, rejected, thrown } }];
    """
    raw = '{\n  "t": "número"\n}\n'.encode()
    (out,) = run_code_node(js, [webhook_item(raw, {}, {"t": "número"})])
    assert base64.b64decode(out["b64"]) == raw
    assert out["rawBodyType"] == "undefined"
    assert out["rejected"] is True
    # What n8n rejected with, described past its JSON: an Error serialises to `{}`
    # too, so the value alone could not tell the harness's `{}` from an Error.
    captured = {k: v for k, v in FIXTURE["code_node_saw"]["missingPropertyError"].items() if k != "rejected"}
    assert out["thrown"] == captured


def test_n8n_delivers_a_slack_form_body_as_binary_too() -> None:
    saw = FIXTURE["code_node_saw_form"]
    sent = base64.b64decode(FIXTURE["sent_form_body_base64"])
    assert saw["rawBodyType"] == "undefined"
    assert base64.b64decode(saw["helperBytesBase64"]) == sent
    assert saw["item"]["binary"]["data"]["mimeType"] == "application/x-www-form-urlencoded"
    assert isinstance(saw["item"]["json"]["body"], dict)
