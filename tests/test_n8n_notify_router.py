"""The routing table inside `notify-router.json` (NOTIFY-001, NOTIFY-002, ADR-044).

`make notify-smoke` drives the live webhook with `page` and `log` envelopes only,
so the router's domain branches (`vault`, `deploy`, `agent`) were never executed
by any test. This runs the committed Code node in node against every envelope
shape the contract names, and holds each to its Apprise tag.

The second test is the one a table cannot give: every tag the router can emit
must be a tag Apprise routes. Apprise drops a notification whose tag matches no
URL, and n8n still answers 200, so a router tag with no route is a silent loss.
The set of routed tags is read from `_SLACK_ROUTES`, not copied here.
"""

from __future__ import annotations

import itertools
import shutil
from typing import Any

import pytest

from tests.n8n_code_node import node_js, run_items_node
from toolkit.features.k8s_secrets import _SLACK_ROUTES

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

ROUTER_JS = node_js("notify-router.json", "Route by severity")


def _route(envelope: dict[str, Any]) -> dict[str, Any]:
    # The Webhook node hands the parsed request under `body`.
    return run_items_node(ROUTER_JS, [{"body": envelope}])


@pytest.mark.parametrize(
    ("domain", "severity", "tag", "type_"),
    [
        ("ops", "page", "page", "failure"),
        ("ops", "critical", "page", "failure"),
        ("ops", "error", "page", "failure"),
        ("ops", "log", "log", "info"),
        ("ops", "notice", "log", "info"),
        ("ops", "", "log", "info"),
        ("ops", "made-up", "log", "info"),
        ("vault", "page", "vault", "failure"),
        ("vault", "log", "vault", "info"),
        ("deploy", "page", "deploy", "failure"),
        ("deployment", "log", "deploy", "info"),
        ("gitops", "log", "deploy", "info"),
        ("agent", "page", "agent", "failure"),
        ("agents", "log", "agent", "info"),
        ("hermes", "log", "agent", "info"),
        ("VAULT", "PAGE", "vault", "failure"),
    ],
)
def test_each_envelope_routes_to_its_tag(domain: str, severity: str, tag: str, type_: str) -> None:
    out = _route({"domain": domain, "severity": severity, "title": "t", "body": "b", "source": "test"})
    assert (out["tag"], out["type"]) == (tag, type_)


def test_a_resolved_event_is_never_sent_as_a_failure() -> None:
    out = _route({"domain": "ops", "severity": "page", "status": "resolved", "title": "t", "body": "b"})
    assert out["type"] == "info"


def test_every_tag_the_router_emits_is_a_tag_apprise_routes() -> None:
    routed = {tag for tag, *_ in _SLACK_ROUTES}
    domains = ["", "ops", "vault", "deploy", "deployment", "gitops", "agent", "agents", "hermes", "status"]
    severities = ["", "page", "critical", "error", "warning", "notice", "log", "resolved"]
    emitted = {
        _route({"domain": d, "severity": s, "title": "t", "body": "b"})["tag"]
        for d, s in itertools.product(domains, severities)
    }
    assert emitted <= routed, f"router emits tags Apprise does not route: {sorted(emitted - routed)}"
