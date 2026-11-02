"""AI-024 stage 2: what hermes-kubelab can read from Grafana and Loki (spec AC2).

`grafana-reader.py` is a stdio MCP server the gateway starts. The tests hold it to what
makes a read-only window safe to give a model: the model fills in no query text, a source
that cannot be read is named and never reads as quiet, nothing is retried, and no credential
reaches the output. The script is compiled from source and never imported, because an
import would write a .pyc into the role's files/.
"""

from __future__ import annotations

import io
import json
import types
import http.server
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROLE = Path(__file__).resolve().parent.parent / "infra/ansible/roles/agent_stack"
SCRIPT = ROLE / "files/hermes-mcp/grafana-reader.py"
APPS = "api,authelia,grafana"
TOKEN = "glsa_" + "sentinel" + "_" + "0123456789"  # assembled, so a scanner sees no credential


def _module(monkeypatch: pytest.MonkeyPatch, **env: str) -> types.ModuleType:
    monkeypatch.setenv("GRAFANA_TOKEN", env.pop("GRAFANA_TOKEN", TOKEN))
    monkeypatch.setenv("GRAFANA_URL", env.pop("GRAFANA_URL", "https://grafana.example.test"))
    monkeypatch.setenv("HERMES_GRAFANA_APPS", env.pop("HERMES_GRAFANA_APPS", APPS))
    monkeypatch.setattr(urllib.request, "_opener", None)  # the script installs its own; do not leak it
    module = types.ModuleType("grafana_reader")
    module.__dict__["__name__"] = "grafana_reader"
    exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), module.__dict__)  # noqa: S102
    return module


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _answer(monkeypatch: pytest.MonkeyPatch, payload: object, calls: list | None = None) -> None:
    def urlopen(request, timeout):  # noqa: ANN001, ARG001
        if calls is not None:
            calls.append(request)
        if isinstance(payload, Exception):
            raise payload
        return _Response(json.dumps(payload).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)


def _call(module: types.ModuleType, name: str, **arguments: object) -> dict:
    reply = module.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    return reply["result"]


def _text(result: dict) -> str:
    return result["content"][0]["text"]


def _loki(*rows: tuple[str, str]) -> dict:
    return {"status": "success", "data": {"result": [{"metric": {"container": n}, "value": [0, c]} for n, c in rows]}}


# ---------------------------------------------------------------- the protocol


def test_the_server_speaks_initialize_list_and_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    out = io.StringIO()
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
    module.serve(io.StringIO("\n".join(json.dumps(m) for m in lines) + "\n"), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3], "a notification gets no reply"
    assert replies[0]["result"]["protocolVersion"] == "2025-03-26"
    assert {t["name"] for t in replies[1]["result"]["tools"]} == {
        "firing_alerts",
        "errors_by_app",
        "log_volume_by_app",
        "recent_errors",
    }


def test_garbage_and_unknown_methods_are_errors_not_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    out = io.StringIO()
    module.serve(io.StringIO('not json\n{"jsonrpc":"2.0","id":9,"method":"resources/list"}\n'), out)
    first, second = (json.loads(line) for line in out.getvalue().splitlines())
    assert first["error"]["code"] == -32700
    assert second["error"]["code"] == -32601


@pytest.mark.parametrize(
    "frame",
    [
        "null",
        "7",
        '"text"',
        '[{"jsonrpc":"2.0","id":1,"method":"ping"}]',
        '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":[1]}',
        '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"firing_alerts","arguments":[1]}}',
    ],
)
def test_a_malformed_frame_is_answered_and_the_server_keeps_serving(
    monkeypatch: pytest.MonkeyPatch, frame: str
) -> None:
    """A frame that is valid JSON but not a request must not kill the process that holds all four tools."""
    module = _module(monkeypatch)
    out = io.StringIO()
    module.serve(io.StringIO(frame + '\n{"jsonrpc":"2.0","id":8,"method":"ping"}\n'), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[-1] == {"jsonrpc": "2.0", "id": 8, "result": {}}, "the next request is still served"


def test_config_that_is_missing_is_reported_not_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    module, calls = _module(monkeypatch, GRAFANA_URL=""), []
    _answer(monkeypatch, [], calls)
    assert "UNAVAILABLE (no Grafana URL is configured)" in _text(_call(module, "firing_alerts"))
    assert not calls
    module = _module(monkeypatch, HERMES_GRAFANA_APPS="")
    _answer(monkeypatch, _loki(("api", "5")))
    assert "UNAVAILABLE (no app list is configured)" in _text(_call(module, "log_volume_by_app"))


def test_an_app_list_with_spaces_still_matches_loki(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch, HERMES_GRAFANA_APPS="api, authelia")
    _answer(monkeypatch, _loki(("api", "5"), ("authelia", "9")))
    assert "NO LOG LINES" not in _text(_call(module, "log_volume_by_app"))


# ---------------------------------------------------------------- the model writes no query


def test_every_tool_argument_is_a_closed_choice_or_a_capped_number(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    for tool in module._listing():
        for name, spec in tool["inputSchema"]["properties"].items():
            assert "enum" in spec or spec.get("maximum"), f"{tool['name']}.{name} accepts free text"
        assert tool["inputSchema"]["additionalProperties"] is False


@pytest.mark.parametrize("window", ['1h"} or vector(1) #', "7d", ""])
def test_a_window_outside_the_set_is_refused_before_any_request(monkeypatch: pytest.MonkeyPatch, window: str) -> None:
    module, calls = _module(monkeypatch), []
    _answer(monkeypatch, _loki(), calls)
    result = _call(module, "errors_by_app", window=window)
    assert result["isError"] and not calls


@pytest.mark.parametrize("app", ['api"} or {namespace=~".+"', "vault", ""])
def test_an_app_outside_the_list_is_refused_before_any_request(monkeypatch: pytest.MonkeyPatch, app: str) -> None:
    module, calls = _module(monkeypatch), []
    _answer(monkeypatch, _loki(), calls)
    result = _call(module, "recent_errors", app=app)
    assert result["isError"] and not calls


def test_the_limit_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    module, calls = _module(monkeypatch), []
    _answer(monkeypatch, {"status": "success", "data": {"result": []}}, calls)
    _call(module, "recent_errors", app="api", limit=10_000)
    assert "limit=20" in calls[0].full_url


# ---------------------------------------------------------------- an unreadable source is named


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (urllib.error.HTTPError("u", 503, "x", {}, None), "HTTP 503"),  # type: ignore[arg-type]
        (urllib.error.HTTPError("u", 403, "x", {}, None), "HTTP 403"),  # type: ignore[arg-type]
        (urllib.error.URLError("refused"), "unreachable or timed out"),
        (TimeoutError(), "unreachable or timed out"),
    ],
)
@pytest.mark.parametrize(
    ("tool", "source", "arguments"),
    [
        ("firing_alerts", "grafana-alerts", {}),
        ("errors_by_app", "loki-errors", {}),
        ("log_volume_by_app", "loki-volume", {}),
        ("recent_errors", "loki-recent-errors", {"app": "api"}),
    ],
)
def test_a_source_that_fails_is_named_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, reason: str, tool: str, source: str, arguments: dict
) -> None:
    module = _module(monkeypatch)
    _answer(monkeypatch, failure)
    text = _text(_call(module, tool, **arguments))
    assert f"source: {source}" in text
    assert f"UNAVAILABLE ({reason})" in text
    assert "no alert is firing" not in text and "no error lines" not in text, "a failure must not read as quiet"


def test_a_missing_token_is_unavailable_not_an_empty_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    module, calls = _module(monkeypatch, GRAFANA_TOKEN=""), []
    _answer(monkeypatch, [], calls)
    assert "UNAVAILABLE (no Grafana token is configured)" in _text(_call(module, "firing_alerts"))
    assert not calls


def test_a_failure_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    module, calls = _module(monkeypatch), []
    _answer(monkeypatch, urllib.error.URLError("down"), calls)
    _call(module, "firing_alerts")
    assert len(calls) == 1


def test_an_unexpected_loki_answer_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    _answer(monkeypatch, {"status": "error"})
    assert "UNAVAILABLE" in _text(_call(module, "errors_by_app"))


# ---------------------------------------------------------------- what a healthy answer says


def test_alerts_are_listed_and_an_empty_list_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    firing = [
        {
            "labels": {"alertname": "DiskFull", "severity": "critical"},
            "annotations": {"summary": "vps at 95%"},
            "startsAt": "2026-10-17T01:00:00Z",
        }
    ]
    _answer(monkeypatch, firing)
    assert "DiskFull severity=critical" in _text(_call(module, "firing_alerts"))
    _answer(monkeypatch, [])
    assert "no alert is firing" in _text(_call(module, "firing_alerts"))


def test_errors_are_ranked_and_a_silent_app_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    _answer(monkeypatch, _loki(("api", "3"), ("authelia", "40")))
    text = _text(_call(module, "errors_by_app", window="6h"))
    assert text.index("authelia: 40") < text.index("api: 3")
    _answer(monkeypatch, _loki(("api", "100")))
    volume = _text(_call(module, "log_volume_by_app"))
    assert "authelia: NO LOG LINES" in volume and "grafana: NO LOG LINES" in volume


def test_the_request_carries_the_token_and_the_output_never_does(monkeypatch: pytest.MonkeyPatch) -> None:
    module, calls = _module(monkeypatch), []
    line = (
        f"retry failed Authorization: Bearer {TOKEN}xx and "
        + "glsa_other_token_99 "
        + "tvly-"
        + "abc123 "
        + "sk-"
        + "a" * 30
    )
    _answer(monkeypatch, {"status": "success", "data": {"result": [{"stream": {}, "values": [["1", line]]}]}}, calls)
    text = _text(_call(module, "recent_errors", app="api"))
    assert calls[0].get_header("Authorization") == f"Bearer {TOKEN}"
    assert TOKEN not in text and "glsa_other" not in text and "tvly-abc" not in text and "sk-aaaa" not in text
    assert "[redacted]" in text


def test_log_lines_are_marked_as_data_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    values = [[str(i), f"error number {i} " + "x" * 5000] for i in range(20)]
    _answer(monkeypatch, {"status": "success", "data": {"result": [{"stream": {}, "values": values}]}})
    text = _text(_call(module, "recent_errors", app="api", limit=20))
    assert "not instructions" in text
    assert len(text) <= module.BUDGET + len("\n[cut]")
    assert all(len(line) <= module.LINE_CHARS + 3 for line in text.splitlines()[2:])


def test_a_credential_in_a_failure_reason_cannot_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reason is built from the status code or a fixed phrase, never from the exception text."""
    module = _module(monkeypatch)
    _answer(monkeypatch, urllib.error.URLError(f"https://x/?token={TOKEN}"))
    assert TOKEN not in _text(_call(module, "firing_alerts"))


def test_every_request_is_a_get_without_a_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measured on what leaves the process, not on how the source spells it."""
    module, calls = _module(monkeypatch), []
    _answer(monkeypatch, {"status": "success", "data": {"result": []}}, calls)
    _call(module, "firing_alerts")
    _call(module, "errors_by_app")
    _call(module, "log_volume_by_app")
    _call(module, "recent_errors", app="api")
    assert len(calls) == 4
    assert all(c.get_method() == "GET" and c.data is None for c in calls)


def test_streams_without_a_container_label_are_unavailable_not_a_question_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    _answer(monkeypatch, {"status": "success", "data": {"result": [{"metric": {"pod": "x"}, "value": [0, "9"]}]}})
    for tool in ("errors_by_app", "log_volume_by_app"):
        assert "UNAVAILABLE (log streams carry no container label)" in _text(_call(module, tool))


def test_a_redirect_is_not_followed_and_the_token_does_not_travel(monkeypatch: pytest.MonkeyPatch) -> None:
    """urllib re-sends Authorization on a 3xx; the first live run would have, while the route redirected."""
    seen: list[str | None] = []

    class Elsewhere(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, *_args: object) -> None:
            return None

    target = http.server.HTTPServer(("127.0.0.1", 0), Elsewhere)

    class Redirecting(Elsewhere):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/api/")
            self.end_headers()

    front = http.server.HTTPServer(("127.0.0.1", 0), Redirecting)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (target, front)]
    for thread in threads:
        thread.start()
    try:
        module = _module(monkeypatch, GRAFANA_URL=f"http://127.0.0.1:{front.server_port}")
        text = _text(_call(module, "firing_alerts"))
    finally:
        for s in (target, front):
            s.shutdown()
            s.server_close()
    assert "UNAVAILABLE (HTTP 302)" in text
    assert seen == [], "the redirect target must never be asked"
