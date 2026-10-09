"""Open WebUI's public name (#2135, ADR-068 D5 amended).

Prod Traefik serves chat.kubelab.live and forwards to ace2 over the tailnet.
Sign-in is the app's own OIDC, so the one thing the route itself must enforce
is that the break-glass password endpoint is never forwarded (lesson-520).
Read from the rendered prod overlay, never from the file, as the gotchas ask.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
WEBUI = COMMON["apps"]["services"]["ai"]["open_webui"]
ACE2 = COMMON["networking"]["nodes"]["ace2"]


def _prod() -> list[dict]:
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays/prod")], check=True, capture_output=True, text=True
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _one(docs: list[dict], kind: str, name: str) -> dict:
    [doc] = [d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name]
    return doc


def test_the_route_forwards_the_public_name_to_ace2_over_the_tailnet() -> None:
    docs = _prod()
    route = _one(docs, "IngressRoute", "open-webui")
    main = route["spec"]["routes"][0]
    assert main["match"] == f"Host(`{WEBUI['domain']}`)"
    assert [m["name"] for m in main["middlewares"]][-1] == "error-pages", "a powered-off ace2 answers the error page"
    [endpoint] = _one(docs, "EndpointSlice", "open-webui-external")["endpoints"]
    assert endpoint["addresses"] == [ACE2["tailscale_ip"]]
    [port] = _one(docs, "EndpointSlice", "open-webui-external")["ports"]
    assert port["port"] == WEBUI["default_port"]


def test_the_password_endpoint_is_refused_on_the_public_name() -> None:
    docs = _prod()
    rules = _one(docs, "IngressRoute", "open-webui")["spec"]["routes"]
    [deny] = [r for r in rules if "/api/v1/auths/signin" in r["match"]]
    assert deny["match"] == f"Host(`{WEBUI['domain']}`) && PathPrefix(`/api/v1/auths/signin`)"
    assert "deny-all" in [m["name"] for m in deny["middlewares"]]
    # Traefik ranks rules by length unless a priority says otherwise: none may.
    assert all("priority" not in r for r in rules)
    allowed = _one(docs, "Middleware", "deny-all")["spec"]["ipAllowList"]["sourceRange"]
    assert allowed == ["127.0.0.1/32"], "no client address is loopback once it reaches Traefik"


def test_the_public_name_has_a_dns_record() -> None:
    import json

    records = json.loads((REPO / "infra/terraform/dns/services.json").read_text())
    [record] = [r for r in records if f"{r['name']}.kubelab.live" == WEBUI["domain"]]
    assert record["environments"] == ["prod"]
    assert "target" not in record, "the record is the VPS's, which reaches ace2 over the tailnet"
