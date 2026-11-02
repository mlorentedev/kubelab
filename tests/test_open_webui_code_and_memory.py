"""Open WebUI runs code and remembers across chats by default (spec AI-025, #2915).

Both exist in v0.12.5 out of the box: the code interpreter runs Python in the
browser (Pyodide), and memory is on for each user. What a chat lacked was the
code interpreter switched on, and anything that saved a memory unless asked.
"""

from __future__ import annotations

import json

from tests.test_agent_stack_role import _common, _env


def _memory() -> dict:
    return _common()["apps"]["services"]["ai"]["open_webui"]["memory"]


def test_every_chat_starts_with_the_code_interpreter_on() -> None:
    raw = _env()["DEFAULT_MODEL_METADATA"]
    assert "code_interpreter" in json.loads(raw[1:-1])["defaultFeatureIds"]


def test_code_runs_in_the_browser_not_on_ace2() -> None:
    """Pyodide runs model-written code in the operator's browser. Jupyter would
    run it in a container on ace2 (operator decision, 2026-11-01)."""
    env = _env()
    assert env["ENABLE_CODE_INTERPRETER"] == "true"
    assert env["CODE_INTERPRETER_ENGINE"] == "pyodide"
    assert env["CODE_EXECUTION_ENGINE"] == "pyodide"


def test_memories_are_saved_without_being_asked() -> None:
    """Off by default in v0.12.5: a memory was saved only when the model chose to
    call its tool. The review reads the chat every N user turns (`utils/memory.py`)."""
    env = _env()
    assert env["ENABLE_MEMORIES"] == "true"
    assert env["ENABLE_MEMORY_BACKGROUND_REVIEW"] == "true"
    assert env["MEMORIES_REVIEW_INTERVAL_TURNS"] == str(_memory()["review_interval_turns"])
    assert 1 <= _memory()["review_interval_turns"] <= 10
