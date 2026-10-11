"""The LAN resolver must send every prod route's name to the router that serves it.

rpi4's CoreDNS answers the prod zone from an explicit `hosts` list, so LAN nodes
can reach prod over the tailnet. Each entry names a node. When a service moves
behind prod K3s Traefik and its entry still names the node the workload runs
on, the name resolves to a host that serves nothing on 443.

That happened to `status.kubelab.live` (#2212). Uptime Kuma runs on rpi3 at
`:3001`, but its public name is an IngressRoute on prod Traefik (#121). The
entry kept rpi3's tailnet address, and every backup heartbeat a LAN node sent
by that name failed to connect, depending on which resolver systemd-resolved
was using at the time.

This renders the template's prod zone from the SSOT and checks each name that
has a prod IngressRoute against the VPS address.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/coredns"
COMMON = REPO / "infra/config/values/common.yaml"


SERVICES_JSON = REPO / "infra/terraform/dns/services.json"


def _role_vars() -> dict:
    """The role defaults the prod zone reads, rendered against common.yaml.

    `coredns_public_records` is a controller-side file lookup in the role; here
    it is the same file read directly.
    """
    common = yaml.safe_load(COMMON.read_text())
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert "services.json" in defaults["coredns_public_records"], (
        "the role no longer reads the public records list; this test reads the wrong source"
    )
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)

    def render(value):
        if isinstance(value, str):
            return env.from_string(value).render(common=common)
        if isinstance(value, dict):
            return {k: render(v) for k, v in value.items()}
        return value

    ctx = {k: render(defaults[k]) for k in ("base_domain", "node_ips", "service_domains", "vps_public_ip")}
    ctx["coredns_public_records"] = json.loads(SERVICES_JSON.read_text())
    return ctx


def _prod_zone() -> dict[str, str]:
    """name -> address, as the rendered prod zone's hosts block answers it."""
    text = (ROLE / "templates/Corefile.j2").read_text()
    zone = text.split("# --- Prod zone ---", 1)[1]
    rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(zone).render(**_role_vars())
    hosts_block = rendered.split("hosts {", 1)[1].split("fallthrough", 1)[0]
    answers: dict[str, str] = {}
    for line in hosts_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        address, name = line.split()
        assert name not in answers, f"{name} is listed twice in the prod zone"
        answers[name] = address
    assert answers, "rendered no entries from the prod zone"
    return answers


def _prod_route_hosts() -> set[str]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl is not installed")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays/prod")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    hosts: set[str] = set()
    for doc in yaml.safe_load_all(out):
        if not doc or doc.get("kind") != "IngressRoute":
            continue
        for route in doc["spec"].get("routes", []):
            hosts.update(re.findall(r"Host\(`([^`]+)`\)", route.get("match", "")))
    assert hosts, "found no IngressRoute hosts in the prod overlay"
    return hosts


def test_every_prod_route_name_resolves_to_the_vps() -> None:
    ctx = _role_vars()
    zone = _prod_zone()
    base = ctx["base_domain"]
    # A staging name on a shared base route is not a prod name: staging resolves
    # through its own zone, above this one.
    routes = {
        h
        for h in _prod_route_hosts()
        if (h == base or h.endswith("." + base)) and not h.endswith(".staging." + base)
    }
    exceptions = {ctx["service_domains"]["vpn"]: ctx["vps_public_ip"]}
    missing = sorted(routes - zone.keys())
    assert not missing, (
        f"prod routes the LAN resolver does not pin: {missing}. Add their record to services.json; "
        "the zone is rendered from it."
    )
    wrong = {h: zone[h] for h in routes if zone[h] != exceptions.get(h, ctx["node_ips"]["vps"])}
    assert not wrong, f"prod route names the LAN resolver sends somewhere other than prod Traefik: {wrong}"


def test_every_pinned_name_is_served() -> None:
    """The reverse: a pin for a name nothing serves is a stale record, not a harmless one."""
    ctx = _role_vars()
    routes = _prod_route_hosts()
    node_served = {
        f"{r['name']}.{ctx['base_domain']}" for r in ctx["coredns_public_records"] if r.get("target")
    }
    declared_elsewhere = {ctx["service_domains"]["jetson"]}  # retirement is #964
    stale = sorted(set(_prod_zone()) - routes - node_served - declared_elsewhere)
    assert not stale, f"the LAN resolver pins names no prod route serves: {stale}"


def test_the_check_covers_uptime_kuma() -> None:
    """Guard the guard: the name that broke must be one the test actually checks."""
    domain = yaml.safe_load(COMMON.read_text())["apps"]["services"]["observability"]["uptime_kuma"]["domain"]
    assert domain in _prod_zone()
    assert domain in _prod_route_hosts()
