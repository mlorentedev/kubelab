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
    return _common()["apps"]["services"]["ai"]["open_webui"]["models"]


def _configs() -> dict:
    raw = _env()["OPENAI_API_CONFIGS"]
    # Single-quoted for Compose's env_file parser, which keeps the JSON as written.
    assert raw.startswith("'") and raw.endswith("'"), raw
    return json.loads(raw[1:-1])


def test_the_nan_connection_offers_only_the_declared_chat_models() -> None:
    nan = _configs()["0"]
    assert nan["enable"] is True
    # An empty allowlist would render as valid JSON and offer nothing, or everything.
    assert _models()["chat"], "no chat models declared"
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
    rag = _common()["apps"]["services"]["ai"]["open_webui"]["rag"]
    others = [
        rag["embedding_model"],
        rag["reranking_model"],
        models["speech_to_text"],
        models["text_to_speech"]["model"],
        models["image_generation"]["model"],
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


def test_the_image_request_asks_for_what_nan_answers() -> None:
    """Open WebUI sends `response_format: b64_json` unless the model matches this
    pattern (v0.12.0 `routers/images.py`). NaN was measured answering with a `url`
    to a request without it, so the configured model must match, and only it."""
    raw = _env()["IMAGE_URL_RESPONSE_MODELS_REGEX_PATTERN"]
    assert raw.startswith("'") and raw.endswith("'"), "unquoted, Compose interpolates the `$`"
    pattern = re.compile(raw[1:-1])
    model = _models()["image_generation"]["model"]
    assert pattern.match(model)
    assert not any(pattern.match(m) for m in _models()["chat"])
