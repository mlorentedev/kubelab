"""An on-demand backend that refuses fails the e2e check; one that is silent skips it.

`backend_reachable` is a TCP probe and its two failure modes mean different things:

* a *timeout* or no route: nothing answered. The node is off, or this runner is not on
  the tailnet. Neither is an outage of the service, so the suite skips it.
* a *refusal*: the host answered and said no, so the node is up and nothing is bound to
  the port. That is an outage, and skipping it hides it. Open WebUI on ace2 (#2703) was
  reported "powered off" by every e2e suite while ace2 had been up for a day.

`tests/infra/test_network.py` draws the same line, but only for Gitea on the Beelink;
nothing else catches a refusal, so the e2e probe has to.

This lives outside `tests/e2e/` on purpose: that directory is skipped wholesale when
the target environment is unreachable, and this test needs no environment at all. It
runs the real probe against loopback sockets, or against a `create_connection` that
times out, so no network is touched.
"""

from __future__ import annotations

import errno
import socket
from collections.abc import Iterator

import pytest

from tests.e2e import expectations
from tests.e2e.expectations import BackendRefused, ServiceExpectation, backend_reachable, on_demand_skip_reason

LOOPBACK = "127.0.0.1"


def _declare_backend(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    """Point a declared on-demand backend at a loopback port instead of a tailnet address."""
    monkeypatch.setattr(expectations, "on_demand_target", lambda svc_name, node_key: (LOOPBACK, port))


def _skip_reason() -> str | None:
    return on_demand_skip_reason("some_service", ServiceExpectation(on_demand_backend="some_node"))


@pytest.fixture
def closed_port() -> int:
    """A loopback port nothing listens on: the kernel refuses a connection to it."""
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def listening_port() -> Iterator[int]:
    """A loopback port with a listener; the handshake completes without an accept()."""
    with socket.socket() as server:
        server.bind((LOOPBACK, 0))
        server.listen()
        yield int(server.getsockname()[1])


@pytest.fixture
def silent_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend whose address swallows the SYN: the probe times out."""

    def time_out(*args: object, **kwargs: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", time_out)
    _declare_backend(monkeypatch, 4242)


def test_a_refused_connection_fails_the_check_and_says_the_node_is_up(
    monkeypatch: pytest.MonkeyPatch, closed_port: int
) -> None:
    """The host answered, so no skip reason may come back for a refusal."""
    _declare_backend(monkeypatch, closed_port)

    with pytest.raises(BackendRefused) as failure:
        _skip_reason()

    message = str(failure.value)
    assert "node is up" in message
    assert f"nothing is listening on {LOOPBACK}:{closed_port}" in message


def test_the_probe_itself_raises_on_a_refusal_so_no_caller_can_read_it_as_down(closed_port: int) -> None:
    """Every caller goes through `backend_reachable`; returning False here would skip them all."""
    with pytest.raises(BackendRefused):
        backend_reachable(LOOPBACK, closed_port)


def test_a_timeout_skips_and_names_its_real_causes(silent_host: None) -> None:
    reason = _skip_reason()

    assert reason is not None, "a silent backend must produce a skip reason"
    assert "timeout" in reason
    assert "node off, or this runner is not on the tailnet" in reason
    assert "127.0.0.1:4242" in reason


@pytest.mark.parametrize("code", [errno.ENETUNREACH, errno.EHOSTUNREACH])
def test_no_route_skips_like_a_timeout(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    """Off the tailnet a runner often gets 'no route', which is not a refusal."""

    def no_route(*args: object, **kwargs: object) -> None:
        raise OSError(code, "no route")

    monkeypatch.setattr(socket, "create_connection", no_route)
    _declare_backend(monkeypatch, 4242)

    assert _skip_reason() is not None
    assert backend_reachable(LOOPBACK, 4242) is False


def test_a_reachable_backend_gives_no_skip_reason(monkeypatch: pytest.MonkeyPatch, listening_port: int) -> None:
    _declare_backend(monkeypatch, listening_port)

    assert _skip_reason() is None
    assert backend_reachable(LOOPBACK, listening_port) is True


def test_a_service_with_no_on_demand_backend_is_never_probed() -> None:
    assert on_demand_skip_reason("some_service", ServiceExpectation()) is None
