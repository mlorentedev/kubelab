"""No edge monitor can be satisfied by the errors service (#3156).

Every `*.kubelab.live` host the edge has no rule for, or loses its rule for,
lands on the catch-all and the errors nginx (`edge/errors/nginx.conf`). That
nginx answers 2xx on a few paths of its own, `/health` as a PREFIX among them,
so `/healthz` and `/health` return `200 OK` from it whatever host was asked.
A plain HTTP monitor on such a path therefore stays green while its service
is unreachable. Measured 2026-11-06 during the Argo CD outage (lesson-717):
`https://argo.kubelab.live/healthz` answered 200 while every Argo CD path was
the errors 404.

So a monitor on a path the errors service answers 2xx must be a keyword
monitor, and its keyword must not appear in what the errors service sends.
Argo CD's monitor is held to the same bar on its own path: it must name
something only Argo CD answers.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
SEED = REPO / "infra/config/uptime-kuma/monitors.json"
ERRORS_NGINX = REPO / "edge/errors/nginx.conf"
CATCH_ALL_HOST = re.compile(r".+\.kubelab\.live")

#: Monitors known to measure something other than their service, each with its ticket.
EXEMPT: dict[str, str] = {}


def _seed() -> list[dict]:
    return json.loads(SEED.read_text(encoding="utf-8"))


def _errors_2xx() -> list[tuple[str, bool, str]]:
    """(path, exact, body) for every location the errors nginx answers itself with a 2xx."""
    conf = ERRORS_NGINX.read_text(encoding="utf-8")
    found = []
    for exact, path, block in re.findall(r"location\s+(=\s+)?(/\S*)\s*\{([^}]*)\}", conf):
        answer = re.search(r"return\s+(2\d\d)(?:\s+(['\"])(.*?)\2)?", block, re.S)
        if answer:
            found.append((path, bool(exact), answer.group(3) or ""))
    return found


def _answered_by_errors(path: str) -> list[str]:
    """The bodies the errors nginx sends with a 2xx for `path`."""
    path = path or "/"
    return [body for loc, exact, body in _errors_2xx() if (path == loc if exact else path.startswith(loc))]


def _edge_monitors() -> list[dict]:
    return [m for m in _seed() if m.get("url") and CATCH_ALL_HOST.fullmatch(urlsplit(m["url"]).hostname or "")]


def test_the_errors_service_still_answers_health_itself() -> None:
    """If this goes red the parse broke, and the check below would judge nothing."""
    assert _answered_by_errors("/healthz") == ["OK"]
    assert _answered_by_errors("/") == []


def test_the_parser_models_every_2xx_the_errors_service_answers() -> None:
    """A 2xx in a construct the parser misses (regex location, nested block) would pass the check below vacuously."""
    conf = ERRORS_NGINX.read_text(encoding="utf-8")
    assert len(re.findall(r"return\s+2\d\d\b", conf)) == len(_errors_2xx())


def test_no_edge_monitor_is_satisfied_by_the_errors_service() -> None:
    blind = []
    for monitor in _edge_monitors():
        if monitor["key"] in EXEMPT:
            continue
        bodies = _answered_by_errors(urlsplit(monitor["url"]).path)
        if not bodies:
            continue
        keyword = monitor.get("keyword") or ""
        if monitor["type"] != "keyword" or not keyword or any(keyword in body for body in bodies):
            blind.append(f"{monitor['key']} ({monitor['url']})")
    assert not blind, (
        "these monitors stay green when their service is gone, because the errors service answers "
        f"2xx on their path; make each a keyword monitor naming something only the service sends: {blind}"
    )


def test_the_argo_cd_monitor_names_what_only_argo_cd_answers() -> None:
    argo = next(m for m in _seed() if m["key"] == "services-auth-argo-cd")
    assert urlsplit(argo["url"]).path == "/api/version"
    assert argo["type"] == "keyword" and argo["keyword"] == '"Version":"v'
    assert "aws1" not in argo["description"]


def test_no_exemption_is_stale() -> None:
    keys = {m["key"] for m in _edge_monitors()}
    assert set(EXEMPT) <= keys, f"exempt monitors no longer in the seed: {sorted(set(EXEMPT) - keys)}"


def _ingress_routes(overlay: str) -> list[dict]:
    """Every IngressRoute the overlay renders."""
    if not shutil.which("kubectl"):
        if os.environ.get("CI"):
            pytest.fail("kubectl is required in CI to render the overlays")
        pytest.skip("kubectl not installed")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc and doc.get("kind") == "IngressRoute"]


def _routed_hosts() -> set[str]:
    """Every literal host an IngressRoute serves in either overlay."""
    hosts: set[str] = set()
    for overlay in ("staging", "prod"):
        for doc in _ingress_routes(overlay):
            for route in doc["spec"].get("routes", []):
                hosts |= set(re.findall(r"Host\(`([^`]+)`\)", route["match"]))
    return hosts


def test_every_edge_monitor_checks_a_host_a_route_serves() -> None:
    """A host no route serves lands on the catch-all and is DOWN forever (#3172).

    `pihole.staging.kubelab.live` was retired by OPS-022, and its monitor read the
    errors 404 for three months. A monitor that is always DOWN teaches everyone to
    ignore the list.
    """
    served = _routed_hosts()
    unserved = sorted(
        f"{m['key']} ({urlsplit(m['url']).hostname})"
        for m in _edge_monitors()
        if urlsplit(m["url"]).hostname not in served
    )
    assert not unserved, f"these monitors check a host no IngressRoute serves: {unserved}"


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_the_n8n_health_path_is_answered_by_n8n_not_authelia(overlay: str) -> None:
    """Behind the ForwardAuth, `/healthz` is a 302 to the portal and the monitor reads Authelia (#3167).

    The rule that serves the n8n monitor's path must carry no `authelia` middleware,
    so the monitor goes DOWN when n8n does, and stays UP when only Authelia is down.
    """
    monitor = next(m for m in _seed() if "n8n" in m["key"] and overlay in m["key"])
    url = urlsplit(monitor["url"])
    n8n = next(d for d in _ingress_routes(overlay) if d["metadata"]["name"] == "n8n")
    serving = [
        r
        for r in n8n["spec"]["routes"]
        if f"Host(`{url.hostname}`)" in r["match"] and ("Path" not in r["match"] or f"Path(`{url.path}`)" in r["match"])
    ]
    # Traefik picks the highest priority, then the longest rule, so take the rule it would pick.
    chosen = max(serving, key=lambda r: (r.get("priority", 0), len(r["match"])))
    names = [m["name"] for m in chosen.get("middlewares", [])]
    assert "authelia" not in names, f"{overlay}: {chosen['match']} sends {url.path} through Authelia"
