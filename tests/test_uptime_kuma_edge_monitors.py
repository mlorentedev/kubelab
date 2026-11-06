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
import re
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
SEED = REPO / "infra/config/uptime-kuma/monitors.json"
ERRORS_NGINX = REPO / "edge/errors/nginx.conf"
CATCH_ALL_HOST = re.compile(r".+\.kubelab\.live")

#: Monitors known to measure something other than their service, each with its ticket.
#: n8n's `/healthz` sits behind the Authelia ForwardAuth, so the monitor follows a 302
#: to the portal and reads Authelia's 200 (#3167).
EXEMPT = {
    "services-data-n8n-prod": "#3167",
    "staging-web-n8n-staging": "#3167",
}


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
