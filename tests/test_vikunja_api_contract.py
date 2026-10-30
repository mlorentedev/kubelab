"""The Vikunja client only calls endpoints the server's own swagger lists.

A fake that answers whatever the client asks certifies the endpoint it encodes:
`/namespaces` was removed in Vikunja 1.0 and its unit tests kept passing
(#1701, lesson-440). Here every request the client can make is checked against
the paths recorded from the deployed server (`tests/fixtures/vikunja/`), so a
removed endpoint fails the suite instead of passing it.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from toolkit.features.vikunja_client import VikunjaClient

FIXTURE = Path(__file__).parent / "fixtures" / "vikunja" / "swagger-paths-1.0.0.json"


def _swagger_patterns() -> list[tuple[str, re.Pattern[str], set[str]]]:
    paths = json.loads(FIXTURE.read_text(encoding="utf-8"))["paths"]
    return [(p, re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", p) + "$"), set(m)) for p, m in paths.items()]


def _dummy(param: inspect.Parameter) -> object:
    annotation = str(param.annotation)
    if "int" in annotation:
        return 7
    if "list" in annotation:
        return ["x"]
    if "dict" in annotation:
        return {}
    return "x"


def _recorded_calls() -> list[tuple[str, str, str]]:
    """Call every public client method with dummy arguments; return (method name, verb, path)."""
    calls: list[tuple[str, str, str]] = []
    for name, fn in inspect.getmembers(VikunjaClient, inspect.isfunction):
        if name.startswith("_"):
            continue
        client = VikunjaClient(base_url="https://tasks.example/api/v1", api_token="t")
        client.session = MagicMock()
        response = MagicMock(ok=True, status_code=200, content=b"[]")
        response.json.return_value = []
        client.session.request.return_value = response
        kwargs = {
            p.name: _dummy(p)
            for p in inspect.signature(fn).parameters.values()
            if p.name != "self" and p.default is inspect.Parameter.empty
        }
        getattr(client, name)(**kwargs)
        for call in client.session.request.call_args_list:
            verb, url = call.args[0], call.args[1]
            calls.append((name, verb.lower(), url.removeprefix("https://tasks.example/api/v1")))
    return calls


@pytest.mark.parametrize("method_name,verb,path", _recorded_calls(), ids=lambda v: str(v))
def test_every_client_request_exists_in_the_servers_swagger(method_name: str, verb: str, path: str) -> None:
    patterns = _swagger_patterns()
    matches = [(p, methods) for p, rx, methods in patterns if rx.match(path)]
    assert matches, f"{method_name}: {verb.upper()} {path} is not a path the server serves"
    assert any(verb in methods for _, methods in matches), (
        f"{method_name}: {path} exists but not for {verb.upper()}; the server offers "
        f"{sorted(set().union(*(m for _, m in matches)))}"
    )


def test_the_client_never_targets_the_removed_namespaces_endpoint() -> None:
    assert not [c for c in _recorded_calls() if "/namespaces" in c[2]]
