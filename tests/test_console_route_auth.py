"""The forge console's host is guarded whole by Authelia (CONSOLE-004 AC3).

The console is served by the api binary on a host of its own. Three things keep
it signed-in, and each one fails open alone, so they are held together here
against what each overlay actually renders:

- every rendered rule for the console host goes through the `authelia` ForwardAuth,
  and every one reaches the api Service, so no other door opens on that host;
- the Authelia rule for that host requires a login, and comes before any rule
  that could match it first (the env's wildcard);
- the host the route serves is the one the api is told (`INFRA_FORGE_CONSOLE_DOMAIN`),
  since the api answers /console only for that host.

It also checks that every Middleware a generated route names exists, because a
route naming a missing one is refused by Traefik: the generator emitted
`authelia-auth@kubernetescrd` for any app asking for auth while the object is
`authelia`, unseen until a generated route asked.
"""

from __future__ import annotations

import fnmatch
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = ["staging", "prod"]
AUTHELIA = {
    "staging": ROOT / "infra/k8s/base/services/authelia-config/configuration.yml",
    "prod": ROOT / "infra/k8s/overlays/prod/authelia-config/configuration.yml",
}


@cache
def _rendered(env: str) -> str:
    out = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/k8s/overlays" / env)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def _render(env: str) -> list[dict]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    return [d for d in yaml.safe_load_all(_rendered(env)) if d]


def _console_domain(env: str) -> str:
    """The host the api is told, read from the ConfigMap the overlay renders."""
    domains = {
        d["data"]["INFRA_FORGE_CONSOLE_DOMAIN"]
        for d in _render(env)
        if d.get("kind") == "ConfigMap" and "INFRA_FORGE_CONSOLE_DOMAIN" in (d.get("data") or {})
    }
    assert len(domains) == 1, f"{env}: the api is told {sorted(domains)} as the console host"
    return domains.pop()


@pytest.mark.parametrize("env", OVERLAYS)
def test_console_host_goes_through_authelia_to_the_api(env: str) -> None:
    domain = _console_domain(env)
    rules = [
        rule
        for d in _render(env)
        if d.get("kind") == "IngressRoute"
        for rule in d["spec"]["routes"]
        if f"Host(`{domain}`)" in rule["match"]
    ]
    assert rules, f"{env}: no route serves {domain}, the host the api is told"
    for rule in rules:
        names = [m["name"] for m in rule.get("middlewares") or []]
        assert "authelia" in names, f"{env}: {rule['match']} has no Authelia ForwardAuth: {names}"
        assert [s["name"] for s in rule["services"]] == ["api"], f"{env}: {rule['match']} reaches {rule['services']}"


@pytest.mark.parametrize("env", OVERLAYS)
def test_authelia_requires_a_login_on_the_console_host(env: str) -> None:
    domain = _console_domain(env)
    rules = yaml.safe_load(AUTHELIA[env].read_text(encoding="utf-8"))["access_control"]["rules"]

    def matches(rule: dict) -> bool:
        domains = rule.get("domain")
        domains = [domains] if isinstance(domains, str) else domains or []
        return any(fnmatch.fnmatch(domain, d) for d in domains)

    first = next((r for r in rules if matches(r)), None)  # Authelia applies the first match
    assert first is not None, f"{env}: no Authelia rule covers {domain}"
    assert first.get("policy") in ("one_factor", "two_factor"), f"{env}: first rule for {domain}: {first}"
    assert not first.get("networks") and not first.get("resources"), (
        f"{env}: the first rule for {domain} is scoped, so a request outside it falls through: {first}"
    )


def _declared_middlewares(env: str) -> set[str]:
    return {d["metadata"]["name"] for d in _render(env) if d.get("kind") == "Middleware"}


@pytest.mark.parametrize("env", OVERLAYS)
def test_generated_routes_name_middlewares_that_exist(env: str) -> None:
    declared = _declared_middlewares(env)
    docs = yaml.safe_load_all((ROOT / f"infra/k8s/overlays/{env}/generated/ingress.yaml").read_text(encoding="utf-8"))
    missing = {
        m["name"]
        for doc in docs
        if doc and doc.get("kind") == "IngressRoute"
        for route in doc["spec"]["routes"]
        for m in route.get("middlewares") or []
        if "@" not in m["name"] and m["name"] not in declared
    }
    assert not missing, f"{env}: generated routes name Middlewares that do not exist: {sorted(missing)}"


def test_generator_names_the_authelia_middleware_that_exists() -> None:
    from toolkit.features.generator_k8s import K8sGenerator

    names = K8sGenerator._build_middlewares(object.__new__(K8sGenerator), {}, enable_auth=True)
    for env in OVERLAYS:
        assert set(names) <= _declared_middlewares(env), f"{env}: generator names {names}"
