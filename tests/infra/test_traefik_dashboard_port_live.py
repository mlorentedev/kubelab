"""SEC-005 (#1538): the dashboard port must be closed on the RUNNING host.

`tests/test_traefik_ports_stay_behind_the_firewall.py` renders the
HelmChartConfig and asserts the port is not in the Service. That proves the
declaration. It cannot prove the cluster matches it -- a merged template is not
a deployed one, and the Traefik release actually running may predate the change,
have been patched by hand, or have failed its Helm upgrade silently.

That distinction is not theoretical here. The exposure this guards against was
created by a value that had been committed and correct-looking for months; what
was never checked was what the host actually answered. On 2026-09-02:

    curl http://<vps>:9000/api/overview   -> 200, unauthenticated, from the
                                             public internet, serving prod's
                                             whole routing topology

The address comes from `networking.vps.public_ip` in common.yaml, never a
literal. A test carrying its own copy of the IP keeps passing after the IP
changes, which is a slower way of not testing -- and the evidence posted on
#1538 was hand-typed curls against that literal, which is exactly the habit this
file replaces.
"""

from __future__ import annotations

import os
import socket

import httpx
import pytest
import yaml

pytestmark = pytest.mark.infra

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_COMMON_YAML = os.path.abspath(os.path.join(_REPO_ROOT, "infra/config/values/common.yaml"))

#: The admin surface. Not published, and reachable only through the IngressRoute
#: at traefik.<domain>, which carries Authelia. Both were 200 before the fix.
DASHBOARD_PORT = 9000

#: Probed to prove the HOST is up before concluding anything about 9000. Without
#: this the whole file passes vacuously whenever the VPS is unreachable, which
#: is the failure mode a "the port does not answer" assertion invites.
REACHABLE_PORT = 443

CONNECT_TIMEOUT_S = 6.0


def _common() -> dict:
    with open(_COMMON_YAML, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _public_ip() -> str:
    """The VPS's public address, from the SSOT (CLAUDE.md: never a literal)."""
    return _common()["networking"]["vps"]["public_ip"]


def _port_answers(host: str, port: int) -> bool:
    """True when a TCP connection completes.

    Deliberately a bare TCP connect rather than an HTTP request: the question is
    whether anything is LISTENING and reachable, and an HTTP-level check would
    conflate "nothing listening" with "listening and returning an error". Those
    two must stay distinguishable -- the fix removed the listener, and a 403
    from a still-published port would be a different, weaker outcome.
    """
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def vps_ip() -> str:
    return _public_ip()


@pytest.fixture(scope="module")
def host_is_reachable(vps_ip: str) -> None:
    """Guard the guard: skip when the VPS is unreachable, never pass vacuously.

    A closed port and an unreachable host are the same observation from here --
    a failed TCP connect. So the closed-port assertion below is only meaningful
    once something else on the same host has answered. If 443 is silent too, the
    honest report is CANNOT CHECK, which is not the same as OK.
    """
    if not _port_answers(vps_ip, REACHABLE_PORT):
        pytest.skip(
            f"CANNOT CHECK: {vps_ip}:{REACHABLE_PORT} did not answer, so the host is "
            f"unreachable from here and a silent :{DASHBOARD_PORT} proves nothing. "
            f"This is NOT a pass -- SEC-005 is unverified in this environment."
        )


class TestTheDashboardPortIsClosedOnTheHost:
    def test_the_port_does_not_accept_connections(self, vps_ip: str, host_is_reachable: None) -> None:
        """The invariant, on the running host rather than in the manifest."""
        assert not _port_answers(vps_ip, DASHBOARD_PORT), (
            f"{vps_ip}:{DASHBOARD_PORT} accepted a TCP connection, and port {REACHABLE_PORT} "
            f"answered too, so this is the host and not a network fluke.\n\n"
            f"That port is Traefik's dashboard/API entrypoint. Published, it serves the whole "
            f"routing topology to anyone (#1538), and ufw CANNOT restrict it: klipper-lb "
            f"publishes it as a hostPort and DNAT is evaluated in PREROUTING, upstream of "
            f"ufw's INPUT chain.\n\n"
            f"Check `ports.traefik.expose.default` in the k3s_server HelmChartConfig template "
            f"-- it must be false -- and that the Traefik release actually running has picked "
            f"the change up: `kubectl get svc traefik -n kube-system` must show only web and "
            f"websecure, and the svclb pod must have no lb-tcp-{DASHBOARD_PORT} container."
        )


class TestTheDashboardIsStillServed:
    """Closing the port must not have taken the supported path with it.

    Half of a security fix is proving the thing it protects still works;
    otherwise the cheapest way to pass the test above is to break Traefik.
    """

    def test_the_authenticated_route_redirects_to_authelia(self, host_is_reachable: None) -> None:
        prod_yaml = os.path.abspath(os.path.join(_REPO_ROOT, "infra/config/values/prod.yaml"))
        with open(prod_yaml, encoding="utf-8") as handle:
            domain = yaml.safe_load(handle)["edge"]["traefik"]["domain"]

        try:
            response = httpx.get(f"https://{domain}/dashboard/", follow_redirects=False, timeout=15.0)
        except httpx.HTTPError as exc:
            pytest.fail(
                f"https://{domain}/dashboard/ could not be reached ({exc}). The port-closing "
                f"half of SEC-005 must not remove the supported path -- the dashboard is served "
                f"by `api@internal` through an IngressRoute behind Authelia."
            )

        assert response.status_code in {302, 303, 307}, (
            f"https://{domain}/dashboard/ returned {response.status_code}, expected a redirect "
            f"to Authelia. A 200 here would be worse than the original bug: it would mean the "
            f"dashboard is served WITHOUT the authelia middleware."
        )

        location = response.headers.get("location", "")
        auth_domain = _common()["apps"]["services"]["security"]["authelia"]["domain"]
        assert auth_domain in location, (
            f"The dashboard redirected to {location!r}, which does not point at Authelia "
            f"({auth_domain}). A redirect somewhere else is not authentication."
        )
