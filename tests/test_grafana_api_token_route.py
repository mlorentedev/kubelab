"""AI-024: the one way into Grafana's API without Authelia, and only that way.

hermes-kubelab reads Grafana with a service-account token, which the ForwardAuth
perimeter cannot carry. A request that presents one on /api/ skips Authelia through its own
Traefik route. Authelia's access_control must NOT hold a bypass for the host instead: that
rule cannot see the Authorization header, so it opened the path to Basic credentials too, and
the break-glass password could be tried on the public host without Authelia's regulation.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / "infra/k8s/overlays/prod/patches.yaml"
AUTHELIA = ROOT / "infra/k8s/overlays/prod/authelia-config/configuration.yml"
HOST = "grafana.kubelab.live"


def _routes() -> list[dict]:
    docs = [d for d in yaml.safe_load_all(PATCHES.read_text()) if d]
    route = next(d for d in docs if d["kind"] == "IngressRoute" and d["metadata"]["name"] == "grafana")
    return route["spec"]["routes"]


def _ungated(route: dict) -> bool:
    return "authelia" not in {m["name"] for m in route.get("middlewares", [])}


def test_exactly_one_route_skips_authelia_and_it_needs_a_service_account_token() -> None:
    ungated = [r for r in _routes() if _ungated(r)]
    assert len(ungated) == 1, "only the token route may skip Authelia"
    match = ungated[0]["match"]
    assert f"Host(`{HOST}`)" in match
    assert "PathPrefix(`/api/`)" in match
    regexp = re.search(r"HeadersRegexp\(`Authorization`, `([^`]+)`\)", match)
    assert regexp, "the route must be selected by the Authorization header"
    assert re.fullmatch(regexp.group(1), "Bearer glsa_AbC123_def456")
    assert not re.fullmatch(regexp.group(1), "Basic YnJlYWs6Z2xhc3M="), "Basic credentials must stay behind Authelia"
    assert not re.fullmatch(regexp.group(1), "Bearer eyJhbGciOi"), "only a Grafana service-account token"


def test_the_token_route_outranks_the_gated_one_and_keeps_every_other_guard() -> None:
    token, gated = sorted(_routes(), key=lambda r: -r["priority"])
    assert _ungated(token) and not _ungated(gated)
    guards = {"secure-headers", "rate-limit", "crowdsec-bouncer", "error-pages"}
    assert guards <= {m["name"] for m in token["middlewares"]}


def test_authelia_holds_no_bypass_for_grafana() -> None:
    rules = yaml.safe_load(AUTHELIA.read_text())["access_control"]["rules"]
    grafana = [r for r in rules if r.get("domain") == HOST]
    assert [r["policy"] for r in grafana] == ["one_factor"]
