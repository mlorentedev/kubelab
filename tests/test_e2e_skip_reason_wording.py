"""An on-demand backend that refuses fails the e2e check; one that is silent skips it.

`backend_reachable` is a TCP probe and its two failure modes mean different things:

* a *timeout* or no route: nothing answered. The node is off, or this runner is not on
  the tailnet. Neither is an outage of the service, so the suite skips it.
* a *refusal*: the host answered and said no, so the node is up and nothing is bound to
  the port. That is an outage, and skipping it hides it. Open WebUI on ace2 (#2703) was
  reported "powered off" by every e2e suite while ace2 had been up for a day.

`tests/infra/test_network.py` draws the same line, but only for Gitea on the Beelink;
nothing else catches a refusal, so the e2e probe has to.

`TestOnDemandBackend` is the one caller that keeps testing while the backend refuses: the
public route must still answer the offline status, since an outage is the window in which a
broken route or middleware chain would go unseen. It then fails with the outage. The last
tests drive that test method with a fake HTTP client.

This lives outside `tests/e2e/` on purpose: that directory is skipped wholesale when
the target environment is unreachable, and this test needs no environment at all. It
runs the real probe against loopback sockets, or against a `create_connection` that
times out, so no network is touched.
"""

from __future__ import annotations

import errno
import pathlib
import socket
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from tests.e2e import expectations
from tests.e2e import test_auth_flow as e2e_auth_flow
from tests.e2e import test_content as e2e_content
from tests.e2e import test_health as e2e_health
from tests.e2e import test_security_headers as e2e_headers
from tests.e2e.expectations import (
    EXPECTATIONS,
    OFFLINE_STATUS,
    BackendRefused,
    ServiceExpectation,
    backend_reachable,
    on_demand_skip_reason,
    skip_reason,
)

LOOPBACK = "127.0.0.1"


def _declare_backend(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    """Point a declared on-demand backend at a loopback port instead of a tailnet address."""
    monkeypatch.setattr(expectations, "on_demand_target", lambda svc_name, node_key: (LOOPBACK, port))


def _skip_reason() -> str | None:
    return on_demand_skip_reason("some_service", ServiceExpectation(on_demand_backend="some_node"))


@pytest.fixture
def closed_port() -> Iterator[int]:
    """A loopback port nothing listens on: the kernel refuses a connection to it.

    The socket stays bound, never listening, for the whole test. Closing it
    would free the port, and a listener another worker opens there would turn
    the refusal into a connection."""
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        yield int(probe.getsockname()[1])


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
    # Silence has two causes the probe cannot tell apart, so the reason asserts neither.
    assert "powered off" not in reason
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


def test_a_declared_skip_is_read_before_the_backend_is_probed(
    monkeypatch: pytest.MonkeyPatch, closed_port: int
) -> None:
    """An env that never runs the service has nothing there to probe, so a refusal is not its outage."""
    _declare_backend(monkeypatch, closed_port)
    exp = ServiceExpectation(on_demand_backend="some_node", skip_in_envs=("staging",))

    assert skip_reason("some_service", exp, "staging") == "some_service skipped in staging"
    with pytest.raises(BackendRefused):
        skip_reason("some_service", exp, "prod")


# Every e2e path that reads the probe. A staging run failed the two security-header
# tests on Open WebUI, which only prod runs, because ace2 refused while its image
# store was empty: those tests probed before they read the declaration.
_PROBING_CALLERS = {
    "auth_flow": lambda env: e2e_auth_flow._resolve("open_webui", {}, env),
    "content": lambda env: e2e_content._resolve("open_webui", {}, env),
    "health": lambda env: e2e_health._resolve("open_webui", {}, env),
    "hsts": lambda env: e2e_headers.TestSecurityHeaders().test_hsts_header(
        "open_webui", {}, cast(httpx.Client, None), env
    ),
    "security_headers": lambda env: e2e_headers.TestSecurityHeaders().test_security_headers_present(
        "open_webui", {}, cast(httpx.Client, None), env
    ),
}


@pytest.mark.parametrize("caller", sorted(_PROBING_CALLERS))
def test_a_refusing_backend_skips_an_env_that_never_runs_the_service(
    monkeypatch: pytest.MonkeyPatch, closed_port: int, caller: str
) -> None:
    assert "staging" in EXPECTATIONS["open_webui"].skip_in_envs
    _declare_backend(monkeypatch, closed_port)

    with pytest.raises(pytest.skip.Exception, match="open_webui skipped in staging"):
        _PROBING_CALLERS[caller]("staging")


@pytest.mark.parametrize("caller", sorted(_PROBING_CALLERS))
def test_a_refusing_backend_fails_an_env_that_runs_the_service(
    monkeypatch: pytest.MonkeyPatch, closed_port: int, caller: str
) -> None:
    """The other half: reading the declaration first must not drop the probe where the service runs."""
    assert "prod" not in EXPECTATIONS["open_webui"].skip_in_envs
    _declare_backend(monkeypatch, closed_port)

    # A skip is a BaseException that `pytest.raises` does not catch: it would mark this
    # test skipped, never failed, so a caller that stopped probing would pass unseen.
    try:
        _PROBING_CALLERS[caller]("prod")
    except BackendRefused:
        return
    except pytest.skip.Exception as skipped:
        pytest.fail(f"{caller} skipped prod instead of probing its backend: {skipped}")
    pytest.fail(f"{caller} returned without probing its backend")


def test_no_e2e_test_probes_without_reading_the_declaration() -> None:
    """`skip_reason` is the one place that orders the two; a new caller that probes directly would not be.

    Every module under tests/e2e/ is read, helpers and conftest included, not only test files.
    """
    e2e = pathlib.Path(expectations.__file__).parent
    direct = [
        f.name
        for f in sorted(e2e.glob("*.py"))
        if f.name != "expectations.py" and "on_demand_skip_reason(" in f.read_text(encoding="utf-8")
    ]
    assert direct == [], f"call skip_reason(svc_name, exp, env) instead of on_demand_skip_reason in: {direct}"


def test_a_service_with_no_on_demand_backend_is_never_probed() -> None:
    assert on_demand_skip_reason("some_service", ServiceExpectation()) is None


class _FakeEdge:
    """Stands in for the HTTP client: records the requests and answers with one status."""

    def __init__(self, status: int | None = None, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.requests: list[str] = []

    def get(self, url: str) -> Any:
        self.requests.append(url)
        if self.error:
            raise self.error
        return SimpleNamespace(status_code=self.status)


def _check_route(monkeypatch: pytest.MonkeyPatch, port: int, edge: _FakeEdge) -> None:
    """Run `TestOnDemandBackend` for a declared backend at a loopback port, with a fake edge."""
    monkeypatch.setitem(e2e_health.EXPECTATIONS, "some_service", ServiceExpectation(on_demand_backend="some_node"))
    monkeypatch.setattr(e2e_health, "on_demand_target", lambda svc_name, node_key: (LOOPBACK, port))
    services = {"some_service": SimpleNamespace(domain="some.example.invalid", health_path="/health")}
    e2e_health.TestOnDemandBackend().test_route_is_intact_whether_or_not_the_backend_is_up(
        "some_service", cast(Any, services), cast(httpx.Client, edge), "prod"
    )


def test_a_refusal_still_asserts_the_route_and_then_fails_with_the_outage(
    monkeypatch: pytest.MonkeyPatch, closed_port: int
) -> None:
    """The route is checked in the outage window, and the outage is what fails the test."""
    edge = _FakeEdge(status=OFFLINE_STATUS[0])

    with pytest.raises(BackendRefused) as failure:
        _check_route(monkeypatch, closed_port, edge)

    assert edge.requests == ["https://some.example.invalid/health"], "the route was not asserted before failing"
    assert f"nothing is listening on {LOOPBACK}:{closed_port}" in str(failure.value)


def test_a_refusal_with_a_broken_route_reports_both(monkeypatch: pytest.MonkeyPatch, closed_port: int) -> None:
    """A route that serves 200 from a dead backend is its own failure, and the outage is not lost."""
    with pytest.raises(AssertionError) as failure:
        _check_route(monkeypatch, closed_port, _FakeEdge(status=200))

    message = str(failure.value)
    assert not isinstance(failure.value, BackendRefused), "the route assertion was skipped"
    assert str(OFFLINE_STATUS) in message
    assert f"nothing is listening on {LOOPBACK}:{closed_port}" in message


def test_a_refusal_with_an_edge_timeout_reports_both(monkeypatch: pytest.MonkeyPatch, closed_port: int) -> None:
    with pytest.raises(pytest.fail.Exception) as failure:
        _check_route(monkeypatch, closed_port, _FakeEdge(error=httpx.ReadTimeout("slow")))

    assert "refuses connections" in str(failure.value)
    assert f"nothing is listening on {LOOPBACK}:{closed_port}" in str(failure.value)


def test_a_silent_backend_passes_when_the_route_answers_the_offline_status(
    monkeypatch: pytest.MonkeyPatch, silent_host: None
) -> None:
    _check_route(monkeypatch, 4242, _FakeEdge(status=OFFLINE_STATUS[-1]))


def test_a_live_backend_passes_when_the_route_serves_it(monkeypatch: pytest.MonkeyPatch, listening_port: int) -> None:
    _check_route(monkeypatch, listening_port, _FakeEdge(status=200))
