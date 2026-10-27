"""The e2e skip reason says what the probe measured, not a cause it never saw.

`backend_reachable` is a TCP probe, so a timeout (node off) and a refusal (node up,
nothing listening) both come back False. The conflation is deliberate: the
distinction belongs to `tests/infra/test_network.py`. But the skip message built from
that boolean said the backend "is powered off". On 2026-10-27 it said so for Open WebUI
on ace2 while ace2 had been up for a day and the container's port was simply not bound.

This lives outside `tests/e2e/` on purpose: that directory is skipped wholesale when
the target environment is unreachable, and this test needs no environment at all.
"""

from __future__ import annotations

import pytest

from tests.e2e import expectations
from tests.e2e.expectations import ServiceExpectation, on_demand_skip_reason

#: Not an address from the SSOT: the probe is replaced, so the name is only echoed.
HOST = "node.example.invalid"
PORT = 4242


@pytest.fixture
def unreachable_backend(monkeypatch: pytest.MonkeyPatch) -> str:
    """A declared on-demand backend whose TCP probe fails, without touching any network."""
    monkeypatch.setattr(expectations, "on_demand_target", lambda svc_name, node_key: (HOST, PORT))
    monkeypatch.setattr(expectations, "backend_reachable", lambda host, port, timeout=3.0: False)
    return on_demand_skip_reason("some_service", ServiceExpectation(on_demand_backend="some_node")) or ""


def test_an_unreachable_backend_is_not_called_powered_off(unreachable_backend: str) -> None:
    """A refused connection reaches this branch too, and the node is up then."""
    assert unreachable_backend, "an unreachable declared backend must produce a skip reason"
    assert "is powered off" not in unreachable_backend
    assert "powered off" not in unreachable_backend or "nothing listening" in unreachable_backend


def test_the_skip_reason_names_what_was_probed(unreachable_backend: str) -> None:
    assert f"{HOST}:{PORT}" in unreachable_backend
    assert "not reachable" in unreachable_backend


def test_the_skip_reason_keeps_both_causes_the_probe_cannot_tell_apart(unreachable_backend: str) -> None:
    """Powered off is one of two causes, never the claim."""
    assert "powered off, or nothing listening" in unreachable_backend


def test_a_reachable_backend_gives_no_skip_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(expectations, "on_demand_target", lambda svc_name, node_key: (HOST, PORT))
    monkeypatch.setattr(expectations, "backend_reachable", lambda host, port, timeout=3.0: True)

    assert on_demand_skip_reason("some_service", ServiceExpectation(on_demand_backend="some_node")) is None


def test_a_service_with_no_on_demand_backend_is_never_skipped_on_reachability() -> None:
    assert on_demand_skip_reason("some_service", ServiceExpectation()) is None
