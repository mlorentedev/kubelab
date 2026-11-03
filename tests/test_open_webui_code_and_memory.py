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
    call its tool. The review reads the chat every N user turns (`utils/memory.py`).

    The env is what the instance runs: with ENABLE_PERSISTENT_CONFIG=false
    (asserted in test_agent_stack_role.py), `Config.get()` returns the env value
    and never reads the database row (v0.12.5 `models/config.py`)."""
    env = _env()
    assert env["ENABLE_MEMORIES"] == "true"
    assert env["ENABLE_MEMORY_BACKGROUND_REVIEW"] == "true"
    assert env["MEMORIES_REVIEW_INTERVAL_TURNS"] == str(_memory()["review_interval_turns"])
    # More often than v0.12.5's default of 10, the reason the key is set at all;
    # 0 would never review.
    assert 1 <= _memory()["review_interval_turns"] < 10


def _effective_config_tasks() -> list[dict]:
    from tests.test_agent_stack_role import _tasks

    return [t for t in _tasks() if "/api/v1/configs/export" in str(t.get("ansible.builtin.uri", {}).get("url", ""))]


def test_the_running_instance_is_read_not_only_its_env() -> None:
    """The tests above read the rendered env; this reads what the instance serves
    after a provision (#2970). The export holds every secret the instance has, so
    the read is no_log and only the keys checked are kept."""
    from tests.test_agent_stack_role import _tasks

    [read] = _effective_config_tasks()
    assert read.get("no_log") is True
    assert "Bearer" in str(read["ansible.builtin.uri"]["headers"]["Authorization"])
    checks = " ".join(str(t.get("ansible.builtin.assert", {}).get("that", "")) for t in _tasks())
    for key in (
        "memories.background_review.enable",
        "memories.review_interval_turns",
        "code_interpreter.engine",
    ):
        assert key in checks, f"nothing asserts {key}"
