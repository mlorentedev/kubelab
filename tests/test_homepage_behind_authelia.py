"""#456: prod Homepage is reached only through Authelia, except its health probe.

Homepage's widgets call tailnet-only Glances and Uptime Kuma from the server and
hand the result to whoever asks: before this, `GET home.kubelab.live/api/services`
answered 200 to anyone on the internet (measured 2026-10-17). So the host needs
the `authelia` ForwardAuth, and three things follow from adding it:

- Prod's catch-all `*.kubelab.live` rule admits only the vpn/internal networks, and
  the operator reaches prod through its public IP, so the host needs its own
  one_factor rule or the middleware locks everyone out.
- Uptime Kuma checked `/` for 2xx while following redirects: behind ForwardAuth it
  would follow the 302 to the portal, get a 200 there, and stay green while
  measuring Authelia. Every other protected service is probed on an unauthenticated
  health path, so Homepage's `/api/healthcheck` (it answers `up`) gets a narrow rule
  without the middleware, and the monitor points at it.
- The break-glass declaration grows an entry; `tests/test_break_glass.py` enforces it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOST = "home.kubelab.live"
HEALTH = "/api/healthcheck"
PROD_AUTHELIA = PROJECT_ROOT / "infra/k8s/overlays/prod/authelia-config/configuration.yml"
MONITORS = PROJECT_ROOT / "infra/config/uptime-kuma/monitors.json"


def _prod_homepage_routes() -> list[dict]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: the prod Homepage route was NOT checked")
    out = subprocess.run(
        ["kubectl", "kustomize", str(PROJECT_ROOT / "infra/k8s/overlays/prod")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    docs = [d for d in yaml.safe_load_all(out) if d]
    routes = [
        r
        for d in docs
        if d.get("kind") == "IngressRoute"
        for r in d["spec"]["routes"]
        if f"Host(`{HOST}`)" in r["match"]
    ]
    assert routes, f"no prod IngressRoute rule matches {HOST}"
    return routes


def _middlewares(route: dict) -> list[str]:
    return [m["name"] for m in route.get("middlewares", [])]


def test_every_prod_rule_but_the_health_probe_goes_through_authelia():
    for route in _prod_homepage_routes():
        if HEALTH in route["match"]:
            continue
        assert "authelia" in _middlewares(route), f"{route['match']} serves Homepage without Authelia"


def test_the_health_probe_rule_matches_only_that_path():
    routes = _prod_homepage_routes()
    probes = [r for r in routes if HEALTH in r["match"]]
    assert len(probes) == 1, f"expected one health-probe rule for {HOST}, found {len(probes)}"
    probe = probes[0]
    assert f"Path(`{HEALTH}`)" in probe["match"], "the unauthenticated rule must match the exact path, not a prefix"
    assert "authelia" not in _middlewares(probe)
    others = [r.get("priority", 0) for r in routes if HEALTH not in r["match"]]
    assert probe.get("priority", 0) > max(others), "the probe rule must outrank the Authelia rule"


def test_prod_authelia_admits_the_host_from_any_network():
    rules = yaml.safe_load(PROD_AUTHELIA.read_text(encoding="utf-8"))["access_control"]["rules"]
    own = [r for r in rules if r["domain"] == HOST]
    assert own, f"prod Authelia has no rule for {HOST}; the vpn/internal-only wildcard would deny the public IP"
    assert own[0]["policy"] == "one_factor"
    assert "networks" not in own[0]


def test_the_uptime_kuma_monitor_probes_the_health_path_without_following_redirects():
    monitors = json.loads(MONITORS.read_text(encoding="utf-8"))
    items = monitors if isinstance(monitors, list) else monitors["monitors"]
    homepage = [m for m in items if m.get("url", "").startswith(f"https://{HOST}")]
    assert len(homepage) == 1, f"expected one monitor on {HOST}, found {len(homepage)}"
    monitor = homepage[0]
    assert monitor["url"] == f"https://{HOST}{HEALTH}"
    assert monitor["maxredirects"] == 0, "a redirect would land on the portal and measure Authelia instead"
