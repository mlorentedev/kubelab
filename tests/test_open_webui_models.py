"""Open WebUI offers each NaN model for the one job it does (spec AI-015, #2211).

NaN's key lists every model NaN hosts, and with no `model_ids` Open WebUI offered
all of them in the chat picker: embeddings, the reranker, Whisper, Kokoro and
the image models, which cannot chat, next to models our tier is refused (401).
The declaration in `common.yaml` names each model's job, and the env wires it.
"""

from __future__ import annotations

import json
import re

from tests.test_agent_stack_role import _common, _context, _env


def _models() -> dict:
    return _common()["apps"]["services"]["ai"]["nan"]["models"]


EXPECTED_CHAT = [
    "qwen3.6",
    "gemma4",
    "glm5.3-flash",
    "deepseek-v4-flash",
    "mimo-v2.6-flash",
    "qwen3.8-flash",
    "glm5.3",
    "kimi-k3.1-pro",
    "qwen3.8-max",
    "deepseek-v4-pro",
    "hy4",
]


def _configs() -> dict:
    raw = _env()["OPENAI_API_CONFIGS"]
    # Single-quoted for Compose's env_file parser, which keeps the JSON as written.
    assert raw.startswith("'") and raw.endswith("'"), raw
    return json.loads(raw[1:-1])


def test_the_nan_connection_offers_only_the_declared_chat_models() -> None:
    nan = _configs()["0"]
    assert nan["enable"] is True
    # Live probe 2026-11-13: these 11 answered a completion. `minimax-h3` was
    # listed by /v1/models but returned 403 for this key, so it is not offered.
    assert _models()["chat"] == EXPECTED_CHAT
    assert "minimax-h3" not in _models()["chat"]
    assert nan["model_ids"] == _models()["chat"]


def test_hermes_keeps_offering_what_it_serves() -> None:
    """Connection 1 is Hermes. An entry with empty `model_ids` would be harmless,
    but any `model_ids` there would hide the agent; it gets no entry at all."""
    assert set(_configs()) == {"0"}
    # Key "0" binds by position, so NaN must stay first: swapped, the allowlist
    # would restrict Hermes and leave NaN offering everything.
    urls = _env()["OPENAI_API_BASE_URLS"].split(";")
    assert len(urls) == 2
    assert urls[0] == _context()["agent_stack_nan_api_base_url"]


def test_no_model_has_two_jobs() -> None:
    """A model that cannot chat must never reach the picker, and each feature
    names a different model."""
    models = _models()
    others = [
        models["embedding_model"],
        models["reranking_model"],
        models["speech_to_text"],
        models["text_to_speech"]["model"],
        models["image_generation"]["model"],
        *models["image_generation"]["alternatives"],
    ]
    assert len(models["chat"]) == len(set(models["chat"]))
    assert len(others) == len(set(others))
    assert not set(models["chat"]) & set(others)


def test_speech_and_images_come_from_nan() -> None:
    env = _env()
    base = _context()["agent_stack_nan_api_base_url"]
    key = _context()["agent_stack_nan_api_key"]
    models = _models()
    assert env["AUDIO_STT_ENGINE"] == "openai"
    assert (env["AUDIO_STT_OPENAI_API_BASE_URL"], env["AUDIO_STT_OPENAI_API_KEY"]) == (base, key)
    assert env["AUDIO_STT_MODEL"] == models["speech_to_text"]
    assert env["AUDIO_TTS_ENGINE"] == "openai"
    assert (env["AUDIO_TTS_OPENAI_API_BASE_URL"], env["AUDIO_TTS_OPENAI_API_KEY"]) == (base, key)
    assert env["AUDIO_TTS_MODEL"] == models["text_to_speech"]["model"]
    assert env["AUDIO_TTS_VOICE"] == models["text_to_speech"]["voice"]
    assert env["ENABLE_IMAGE_GENERATION"] == "true"
    assert env["IMAGE_GENERATION_ENGINE"] == "openai"
    assert (env["IMAGES_OPENAI_API_BASE_URL"], env["IMAGES_OPENAI_API_KEY"]) == (base, key)
    assert env["IMAGE_GENERATION_MODEL"] == models["image_generation"]["model"]
    assert env["IMAGE_SIZE"] == models["image_generation"]["size"]


def test_every_chat_starts_with_the_image_tool_on() -> None:
    """Off, the model has no `generate_image` tool and improvises one instead:
    measured 2026-11-01, asked for a picture it drew an SVG and created a
    workspace skill to store it. On, native function calling only offers the
    tool (v0.12.5 `utils/tools.py`); it does not generate on every message."""
    raw = _env()["DEFAULT_MODEL_METADATA"]
    assert raw.startswith("'") and raw.endswith("'"), raw
    assert "image_generation" in json.loads(raw[1:-1])["defaultFeatureIds"]
    # The legacy path WOULD generate an image per message (`utils/middleware.py`).
    # In any value, not one variable: `function_calling` could arrive in
    # DEFAULT_MODEL_PARAMS or inside any JSON value. Values, not the raw file, so
    # a comment that names the setting is not an override.
    assert not [k for k, v in _env().items() if "function_calling" in v]


def test_both_image_models_share_one_cap_and_hermes_leaves_open_webui_headroom() -> None:
    """NaN documents 100 requests/month shared by both models, not 100 each.
    Hermes gets a smaller local budget so its calls cannot silently consume the
    whole allowance; NaN remains the cross-consumer authority."""
    image = _models()["image_generation"]
    assert image["model"] == "flux-2-klein"
    assert image["alternatives"] == ["qwen-image-2.1"]
    assert image["monthly_shared_limit"] == 100
    assert 0 < image["hermes_monthly_limit"] < image["monthly_shared_limit"]
    assert image["hermes_monthly_limit"] == 50


def test_the_image_request_asks_for_what_nan_answers() -> None:
    """Open WebUI sends `response_format: b64_json` unless the model matches this
    pattern (v0.12.5 `routers/images.py`). NaN was measured answering with a `url`
    to a request without it, so the configured model must match, and only it."""
    raw = _env()["IMAGE_URL_RESPONSE_MODELS_REGEX_PATTERN"]
    assert raw.startswith("'") and raw.endswith("'"), "unquoted, Compose interpolates the `$`"
    pattern = re.compile(raw[1:-1])
    model = _models()["image_generation"]["model"]
    assert pattern.match(model)
    assert not any(pattern.match(m) for m in _models()["chat"])
