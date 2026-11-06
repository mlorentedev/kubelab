"""Every host behind the Authelia ForwardAuth has its own rule, and no rule trusts a network (SEC-036, #2669).

Authelia decides a ForwardAuth request by the first rule that matches its host.
Both envs had a wildcard catch-all scoped to `networks: [internal]` (prod also
`vpn`), meant as "a login prompt from inside, deny from outside". It never did
that: klipper-lb masquerades every client, so Authelia sees each request,
internet scanners included, from the pod CIDR inside `10.0.0.0/8` (lesson-327,
measured on prod 2026-11-05 and recorded on #1067). `internal` matched everyone
and `vpn` matched no one.

So the rules are explicit per host, and a host nobody listed falls to
`default_policy: deny`. The first test turns that 403 into a CI failure: a new
protected route without a rule fails here rather than in a browser.

The address tests forbid `networks:` and regulation's `ip` mode while #1067 is
open. Authelia's docs recommend `ip` mode, but today it would ban the pod address
every client shares, so one attacker would lock everyone out. Delete those tests
when a real client address reaches Traefik, measured as #1067's acceptance asks,
and not before: until then any address condition is a boundary that only looks
real.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from tests.test_authelia_remember_me_disabled import _SopsPlaceholder
from toolkit.config.constants import AUTHELIA_CONFIG
from toolkit.features.configuration import ConfigurationManager

REPO = Path(__file__).resolve().parent.parent
OVERLAYS = ["staging", "prod"]
AUTHELIA_AUTHZ = "authelia.kubelab.svc.cluster.local"
TEMPLATE = REPO / "infra/config/authelia/templates/configuration.yml.j2"

#: (overlay, host): routes behind the ForwardAuth that no rule serves, each with its ticket.
UNSERVED = {
    ("staging", "dev.kubelab.live"): "#3135: resolves nowhere, outside the staging cookie scope",
    ("staging", "loki.kubelab.live"): "#3135: resolves nowhere, outside the staging cookie scope",
    ("prod", "loki.internal.kubelab.local"): "#3135: a .local name no browser reaches; Vector pushes in-cluster",
}


def _render(overlay: str) -> list[dict]:
    if shutil.which("kubectl") is None:
        # In CI a missing kubectl must fail: a skip would pass every guard here unchecked.
        if os.environ.get("CI"):
            pytest.fail("kubectl not on PATH in CI: the Authelia access rules went unchecked")
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert out.returncode == 0, out.stderr
    return [doc for doc in yaml.safe_load_all(out.stdout) if doc]


def _config(docs: list[dict]) -> dict:
    """From the rendered ConfigMap, so the prod overlay's replacement is what gets judged."""
    (config,) = [d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("authelia-config")]
    return yaml.safe_load(config["data"]["configuration.yml"])


def _access_control(docs: list[dict]) -> dict:
    return _config(docs)["access_control"]


def _dev_config(monkeypatch: pytest.MonkeyPatch) -> dict:
    """The dev template rendered from the loader's values, as `test_authelia_remember_me_disabled` does."""
    manager = ConfigurationManager("dev", REPO)
    monkeypatch.setattr(manager, "_decrypt_sops", lambda _path: {})
    context = {
        **manager.get_env_vars(),
        "apps": [],
        "authelia_users": [],
        "oidc_clients": [],
        **{name: getattr(AUTHELIA_CONFIG, name) for name in dir(AUTHELIA_CONFIG) if name.startswith("ARGON2_")},
    }
    templates = Environment(loader=FileSystemLoader(TEMPLATE.parent), undefined=_SopsPlaceholder)
    return yaml.safe_load(templates.get_template(TEMPLATE.name).render(context))


def _authelia_middlewares(docs: list[dict]) -> set[str]:
    """Every ForwardAuth that asks Authelia, by address rather than by name, so a renamed one still counts."""
    return {
        d["metadata"]["name"]
        for d in docs
        if d["kind"] == "Middleware" and AUTHELIA_AUTHZ in d["spec"].get("forwardAuth", {}).get("address", "")
    }


def _guarded_hosts(docs: list[dict]) -> set[str]:
    middlewares = _authelia_middlewares(docs)
    hosts = set()
    for doc in docs:
        if doc["kind"] != "IngressRoute":
            continue
        for route in doc["spec"].get("routes", []):
            if middlewares & {m["name"] for m in route.get("middlewares") or []}:
                hosts.update(_hosts(route["match"]))
    return hosts


def _hosts(match: str) -> list[str]:
    """Every name in every `Host(...)`, including a multi-argument one."""
    return [name for args in re.findall(r"\bHost\(([^)]*)\)", match) for name in re.findall(r"`([^`]+)`", args)]


def _explicit_domains(access: dict) -> set[str]:
    domains = set()
    for rule in access.get("rules", []):
        listed = rule["domain"] if isinstance(rule["domain"], list) else [rule["domain"]]
        domains.update(d for d in listed if "*" not in d)
    return domains


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_render_measured_the_routes_it_is_judging(overlay: str) -> None:
    """An empty render would pass every assertion below over nothing."""
    assert _authelia_middlewares(_render(overlay)) == {"authelia"}
    assert {f"grafana.{'staging.' if overlay == 'staging' else ''}kubelab.live"} <= _guarded_hosts(_render(overlay))


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_guarded_host_has_its_own_rule(overlay: str) -> None:
    docs = _render(overlay)
    explicit = _explicit_domains(_access_control(docs))
    gaps = sorted(h for h in _guarded_hosts(docs) - explicit if (overlay, h) not in UNSERVED)
    assert not gaps, (
        f"{overlay}: hosts behind an Authelia ForwardAuth with no explicit Authelia rule get "
        f"default_policy deny: {gaps}"
    )


def test_no_unserved_entry_is_stale() -> None:
    """An entry for a host that gained a rule or lost its route is a hole waiting for a reuse."""
    stale = []
    for overlay in OVERLAYS:
        docs = _render(overlay)
        unserved = _guarded_hosts(docs) - _explicit_domains(_access_control(docs))
        stale += [key for key in UNSERVED if key[0] == overlay and key[1] not in unserved]
    assert not stale, stale


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_no_rule_trusts_a_network_while_the_client_address_is_masqueraded(overlay: str) -> None:
    access = _access_control(_render(overlay))
    assert "networks" not in access, f"{overlay}: Authelia `networks` defined while #1067 is open"
    scoped = [r["domain"] for r in access.get("rules", []) if "networks" in r]
    assert not scoped, f"{overlay}: rules scoped by network, which every client matches (#1067): {scoped}"


def test_the_dev_template_trusts_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dev generator rendered `networking.trusted_cidrs` as `internal`; that list is the egress deny list."""
    access = _dev_config(monkeypatch)["access_control"]
    assert "networks" not in access
    assert not [r["domain"] for r in access.get("rules", []) if "networks" in r]
    assert "trusted_cidrs" not in TEMPLATE.read_text(encoding="utf-8")


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_regulation_bans_no_address_while_the_client_address_is_masqueraded(overlay: str) -> None:
    modes = _config(_render(overlay)).get("regulation", {}).get("modes", ["user"])
    assert "ip" not in modes, f"{overlay}: regulation would ban the pod address every client shares (#1067)"


def test_the_dev_regulation_bans_no_address(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "ip" not in _dev_config(monkeypatch).get("regulation", {}).get("modes", ["user"])
