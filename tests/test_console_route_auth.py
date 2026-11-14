"""The forge console's host is guarded whole by Authelia (CONSOLE-004 AC3).

The console has a host of its own, and since ADR-074 D5 two backends behind it: `/console/`
is the api's, everything else is the frontend's nginx (the `console` app). Three things keep
it signed-in, and each one fails open alone, so they are held together here
against what each overlay actually renders:

- every rendered rule for the console host goes through the `authelia` ForwardAuth, and
  reaches the backend D5 gives its path, so no other door opens on that host. While no
  frontend is deployed in an env (no console pin) the embedded page's fallback route is
  the only one, and answers everything from the api;
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


_API_PREFIX = "PathPrefix(`/console/`)"


def _host_rules(docs: list[dict], domain: str) -> list[tuple[str, dict]]:
    """(IngressRoute name, rule) for every rule that serves the console host."""
    return [
        (d["metadata"]["name"], rule)
        for d in docs
        if d.get("kind") == "IngressRoute"
        for rule in d["spec"]["routes"]
        if f"Host(`{domain}`)" in rule["match"]
    ]


def _check_topology(env: str, rules: list[tuple[str, dict]], frontend_deployed: bool) -> None:
    assert rules, f"{env}: no route serves the console host the api is told"
    for name, rule in rules:
        names = [m["name"] for m in rule.get("middlewares") or []]
        assert "authelia" in names, f"{env}: {name} {rule['match']} has no Authelia ForwardAuth: {names}"
        backends = [s["name"] for s in rule["services"]]
        fallback = name == "console-embedded"
        if _API_PREFIX in rule["match"] or fallback or not frontend_deployed:
            assert backends == ["api"], f"{env}: {name} {rule['match']} reaches {backends}, not the api"
        else:
            assert backends == ["console"], f"{env}: {name} {rule['match']} reaches {backends}, not the frontend"


@pytest.mark.parametrize("env", OVERLAYS)
def test_console_host_goes_through_authelia_to_the_backend_its_path_names(env: str) -> None:
    """The committed overlay. A frontend Deployment, once an env pins one, moves everything but
    `/console/` to it; until then the whole host is the api's, as before the frontend."""
    docs = _render(env)
    frontend = any(d.get("kind") == "Deployment" and d["metadata"]["name"] == "console" for d in docs)
    _check_topology(env, _host_rules(docs, _console_domain(env)), frontend_deployed=frontend)


@pytest.mark.parametrize("env", OVERLAYS)
def test_a_pinned_frontend_outranks_the_embedded_fallback_on_every_path(
    env: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The fallback (`priority: 10`) must lose to every generated rule on the host, or a deployed
    frontend would never be reached. Rendered here with a console pin the committed config does
    not have yet, so the check holds the day the first deploy pull request pins one."""
    from toolkit.core.templating import create_renderer
    from toolkit.features import generator_k8s
    from toolkit.features.generator_k8s import K8sGenerator

    real = generator_k8s.ConfigurationManager.get_env_vars
    monkeypatch.setattr(
        generator_k8s.ConfigurationManager,
        "get_env_vars",
        lambda self: {**real(self), "APPS_PLATFORM_CONSOLE_VERSION": "sha-1234567"},
    )
    generator = K8sGenerator()
    out = tmp_path / "ingress.yaml"
    templates = generator.project_root / "infra/k8s/templates"
    assert create_renderer(templates).render_template("ingress.yaml.j2", out, generator._build_context(env))
    generated = [d for d in yaml.safe_load_all(out.read_text(encoding="utf-8")) if d]

    domain = _console_domain(env)
    own = _host_rules(generated, domain)
    assert {n for n, _ in own} == {"console"}, f"{env}: the generated routes on the console host: {own}"
    _check_topology(env, own, frontend_deployed=True)
    assert any(_API_PREFIX in r["match"] for _, r in own), f"{env}: nothing sends /console/ to the api"
    assert any(_API_PREFIX not in r["match"] for _, r in own), f"{env}: nothing serves the frontend"

    def effective(rule: dict) -> int:
        # Traefik gives a router without an explicit priority the LENGTH of its rule.
        return int(rule.get("priority", len(rule["match"])))

    fallback = [r for n, r in _host_rules(_render(env), domain) if n == "console-embedded"]
    assert len(fallback) == 1, f"{env}: expected one embedded fallback rule, found {len(fallback)}"
    assert all(effective(fallback[0]) < effective(r) for _, r in own), (
        f"{env}: the embedded fallback ({effective(fallback[0])}) does not lose to the generated rules"
    )


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
