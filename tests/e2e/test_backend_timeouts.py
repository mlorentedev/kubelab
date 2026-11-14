"""E2E: the edge stops waiting for a stuck backend at its bound, except where declared (OPS-065, ADR-076).

The stuck-backend fixture (staging overlay) accepts a connection and never answers.
Its host runs under the edge's default bound and must answer the edge's own 504 page
once the bound passes (AC1). Its `/exception` rule references a ServersTransport with
no header bound and must still be open past the default (AC2).

Both values come from where they are declared, never from a literal here: the bound
from the `k3s_server` role defaults, the host from the fixture's IngressRoute.
Staging only: the fixture does not ship to prod.
"""

from __future__ import annotations

import pathlib
import re
import time

import httpx
import pytest
import yaml

pytestmark = pytest.mark.e2e

_REPO = pathlib.Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "infra/k8s/overlays/staging/stuck-backend.yaml"
_ROLE_DEFAULTS = _REPO / "infra/ansible/roles/k3s_server/defaults/main.yml"

#: Slack for TLS, the tailnet hop and the error-pages round trip after the cut.
_SLACK_S = 15.0


def _bound_s() -> float:
    raw = str(yaml.safe_load(_ROLE_DEFAULTS.read_text(encoding="utf-8"))["k3s_traefik_response_header_timeout"])
    m = re.fullmatch(r"(\d+)s", raw)
    assert m, f"k3s_traefik_response_header_timeout={raw!r}: expected whole seconds, e.g. 60s"
    return float(m.group(1))


def _host() -> str:
    route = next(
        d
        for d in yaml.safe_load_all(_FIXTURE.read_text(encoding="utf-8"))
        if d and d["kind"] == "IngressRoute" and d["metadata"]["name"] == "stuck-backend"
    )
    hosts = {h for r in route["spec"]["routes"] for h in re.findall(r"Host\(`([^`]+)`\)", r["match"])}
    assert len(hosts) == 1, f"stuck-backend IngressRoute names {sorted(hosts)}; expected one host"
    return hosts.pop()


@pytest.fixture(scope="module")
def _staging_only(env: str) -> None:
    if env != "staging":
        pytest.skip("the stuck-backend fixture ships to staging only")


@pytest.mark.usefixtures("_staging_only")
class TestBackendTimeouts:
    def test_default_route_answers_the_edges_504_at_the_bound(self) -> None:
        bound = _bound_s()
        start = time.monotonic()
        with httpx.Client(timeout=httpx.Timeout(bound + _SLACK_S, connect=10.0)) as client:
            r = client.get(f"https://{_host()}/")
        elapsed = time.monotonic() - start

        assert r.status_code == 504, f"expected the edge's 504, got {r.status_code} after {elapsed:.1f}s"
        assert elapsed >= bound, f"504 after {elapsed:.1f}s, before the {bound:.0f}s bound: not the header timeout"
        assert "<title>504</title>" in r.text, "504 without the edge's error page: error-pages did not intercept it"

    def test_exception_route_stays_open_past_the_bound(self) -> None:
        # The default-route test above reaches the same host through the same edge, so
        # DNS, TLS and the route are known to answer; a read timeout here is the backend.
        wait = _bound_s() + _SLACK_S
        start = time.monotonic()
        with httpx.Client(timeout=httpx.Timeout(wait, connect=10.0)) as client:
            try:
                r = client.get(f"https://{_host()}/exception")
            except httpx.ReadTimeout:
                elapsed = time.monotonic() - start
                assert elapsed >= wait, f"read timeout after {elapsed:.1f}s, before the {wait:.0f}s wait"
                return  # still waiting on the backend past the default bound: the exception holds
        pytest.fail(f"/exception answered {r.status_code} within {wait:.0f}s: the exception's transport is not applied")
