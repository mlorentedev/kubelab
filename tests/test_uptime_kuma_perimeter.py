"""#2483: Uptime Kuma's admin paths sit behind Authelia; its machine and status paths do not.

Kuma has no SSO, so the edge is the only place a sign-in can start at the IdP. But the host
also serves what must work with nobody signed in: the push endpoint every node's backup
heartbeat calls (a 302 there turns into a missed heartbeat and a 3 AM page), public status
pages, badges, and the statics a status page loads. Those paths get their own rule without
the ForwardAuth; the bare host keeps it. The rules are read from the rendered overlays,
because the prod patch replaces the whole `routes:` list and a patch that forgets a rule
renders without complaint.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import cache
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ENVS = ("staging", "prod")


def _host(env: str) -> str:
    """The Kuma host, read from the values SSOT (`apps.services.observability.uptime_kuma.domain`)."""
    from toolkit.features.oidc_clients import load_values

    return load_values(env)["apps"]["services"]["observability"]["uptime_kuma"]["domain"]


HOSTS = {env: _host(env) for env in ENVS}
AUTHELIA = {
    "staging": ROOT / "infra/k8s/base/services/authelia-config/configuration.yml",
    "prod": ROOT / "infra/k8s/overlays/prod/authelia-config/configuration.yml",
}
MONITORS = ROOT / "infra/config/uptime-kuma/monitors.json"

# What a browser with no session, or a machine, must reach. Prefixes end in `/` so that
# `/statusX` or `/api/pushy` do not ride along.
PUBLIC_PREFIXES = {"/status/", "/api/status-page/", "/api/push/", "/api/badge/", "/assets/", "/upload/"}
PUBLIC_PATHS = {
    "/api/entry-page",
    "/robots.txt",
    "/favicon.ico",
    "/icon.svg",
    "/icon-192x192.png",
    "/icon-512x512.png",
    "/apple-touch-icon.png",
    "/manifest.json",
}
# The admin surface: the SPA's own routes and the socket.io channel it runs on.
ADMIN_PATHS = ("/", "/dashboard", "/socket.io/", "/settings/general", "/api/", "/metrics")
GUARDS = {"secure-headers", "rate-limit", "crowdsec-bouncer", "error-pages"}


@cache
def _routes(env: str) -> tuple[dict, ...]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: the Kuma perimeter was NOT checked")
    out = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/k8s/overlays" / env)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    docs = [d for d in yaml.safe_load_all(out) if d]
    route = next(d for d in docs if d["kind"] == "IngressRoute" and d["metadata"]["name"] == "uptime-kuma")
    return tuple(route["spec"]["routes"])


def _middlewares(rule: dict) -> set[str]:
    return {m["name"] for m in rule.get("middlewares", [])}


def _public_rule(env: str) -> dict:
    (rule,) = [r for r in _routes(env) if "authelia" not in _middlewares(r)]
    return rule


def _matches(rule: dict, path: str) -> bool:
    """Whether a path is selected by a rule built only from Host, PathPrefix and Path."""
    match = rule["match"]
    prefixes = re.findall(r"PathPrefix\(`([^`]+)`\)", match)
    exact = re.findall(r"(?<!Prefix)Path\(`([^`]+)`\)", match)
    if not prefixes and not exact:
        return True
    return path in exact or any(path.startswith(p) for p in prefixes)


@pytest.mark.parametrize("env", sorted(HOSTS))
def test_exactly_one_rule_skips_authelia_and_it_names_only_the_public_paths(env: str) -> None:
    rules = _routes(env)
    assert len(rules) == 2, f"{env}: one public rule and one gated rule"
    public = _public_rule(env)
    assert f"Host(`{HOSTS[env]}`)" in public["match"]
    assert set(re.findall(r"PathPrefix\(`([^`]+)`\)", public["match"])) == PUBLIC_PREFIXES
    assert set(re.findall(r"(?<!Prefix)Path\(`([^`]+)`\)", public["match"])) == PUBLIC_PATHS


@pytest.mark.parametrize("env", sorted(HOSTS))
@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_the_admin_surface_never_matches_the_public_rule(env: str, path: str) -> None:
    assert not _matches(_public_rule(env), path), f"{env}: {path} would skip Authelia"


@pytest.mark.parametrize("env", sorted(HOSTS))
def test_the_bare_host_carries_the_forward_auth_last_and_both_rules_keep_the_guards(env: str) -> None:
    (gated,) = [r for r in _routes(env) if "authelia" in _middlewares(r)]
    assert gated["match"] == f"Host(`{HOSTS[env]}`)"
    assert gated["middlewares"][-1]["name"] == "authelia", "ForwardAuth runs after the cheap guards"
    for rule in _routes(env):
        assert GUARDS <= _middlewares(rule), f"{env}: {rule['match']} lost a guard"


@pytest.mark.parametrize("env", sorted(HOSTS))
def test_authelia_gates_the_host_instead_of_bypassing_it(env: str) -> None:
    """With the ForwardAuth on and a `bypass` rule, Authelia answers 200 to everyone: no perimeter at all."""
    rules = yaml.safe_load(AUTHELIA[env].read_text())["access_control"]["rules"]
    policies = [r["policy"] for r in rules if r.get("domain") == HOSTS[env]]
    assert policies == ["one_factor"], f"{env}: {HOSTS[env]} must have one explicit one_factor rule"


def test_the_self_check_probes_a_public_path_and_follows_no_redirect() -> None:
    """Following redirects, a gated URL lands on Authelia's portal, which answers 200: a false UP."""
    monitors = json.loads(MONITORS.read_text())
    (check,) = [m for m in monitors if m["key"] == "services-monitoring-uptime-kuma-prod"]
    url = urlparse(check["url"])
    assert url.hostname == HOSTS["prod"]
    assert url.path in PUBLIC_PATHS
    assert check["maxredirects"] == 0
