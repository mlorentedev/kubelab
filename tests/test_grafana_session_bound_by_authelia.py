"""#1813: Grafana's session ends with Authelia's, and its sign-out goes through Authelia.

Authelia 4.39 has no RP-initiated or back-channel logout, so two things are ours:

- Grafana's own session must not outlive the IdP's. Its defaults are 30 days and 7
  days idle, against Authelia's 8h and 1h, so a demoted or signed-out user kept
  Grafana for weeks. Grafana's two durations equal Authelia's two.
- Signing out of Grafana must end the SSO session too, or "Sign in" with auto-login
  comes straight back as the same user with no prompt. Grafana redirects to
  Authelia's `/logout`, whose `rd` returns to Grafana and so to a fresh login.

The bound Authelia enforces is the `session` block of each overlay's EMITTED
authelia-config, so that is what this reads. Nothing in K8s reads the common.yaml
`session_*` values (the dev Authelia template does), so the dev Authelia is held to
the same numbers. The dev Compose Grafana derives the same three values from the loader variables.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from toolkit.features.configuration import ConfigurationManager

ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = ("staging", "prod")


def _render(overlay: str) -> list[dict[str, Any]]:
    if shutil.which("kubectl") is None:
        pytest.skip(f"kubectl not on PATH: the {overlay} overlay was NOT checked")
    out = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/k8s/overlays" / overlay)], capture_output=True, text=True, check=True
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _configmap(docs: list[dict[str, Any]], prefix: str) -> dict[str, str]:
    maps = [d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"].startswith(prefix)]
    assert len(maps) == 1, f"expected one {prefix} ConfigMap, found {len(maps)}"
    return maps[0]["data"]


def _authelia_and_grafana(overlay: str) -> tuple[dict[str, Any], dict[str, str]]:
    docs = _render(overlay)
    authelia = yaml.safe_load(_configmap(docs, "authelia-config")["configuration.yml"])
    return authelia, _configmap(docs, "grafana-config")


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_grafana_session_lasts_no_longer_than_authelias(overlay: str) -> None:
    authelia, grafana = _authelia_and_grafana(overlay)
    session = authelia["session"]
    assert grafana.get("GF_AUTH_LOGIN_MAXIMUM_LIFETIME_DURATION") == session["expiration"]
    assert grafana.get("GF_AUTH_LOGIN_MAXIMUM_INACTIVE_LIFETIME_DURATION") == session["inactivity"]


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_grafana_signs_out_through_its_own_authelia(overlay: str) -> None:
    authelia, grafana = _authelia_and_grafana(overlay)
    url = urlsplit(grafana.get("GF_AUTH_SIGNOUT_REDIRECT_URL", ""))
    portal = urlsplit(authelia["session"]["cookies"][0]["authelia_url"])
    assert (url.scheme, url.netloc, url.path) == ("https", portal.netloc, "/logout"), f"{overlay}: {url.geturl()!r}"
    # `rd` must come back to this Grafana: Authelia follows it only inside its cookie
    # domain, and a host it refuses leaves the user on the portal with no error.
    back = urlsplit(parse_qs(url.query).get("rd", [""])[0])
    assert back.netloc == urlsplit(grafana["GF_SERVER_ROOT_URL"]).netloc


OIDC_ENDPOINTS = {
    "GF_AUTH_GENERIC_OAUTH_AUTH_URL": "/api/oidc/authorization",
    "GF_AUTH_GENERIC_OAUTH_TOKEN_URL": "/api/oidc/token",
    "GF_AUTH_GENERIC_OAUTH_API_URL": "/api/oidc/userinfo",
}


@pytest.mark.parametrize("overlay", OVERLAYS)
@pytest.mark.parametrize("key", sorted(OIDC_ENDPOINTS))
def test_grafana_oauth_endpoints_name_its_own_authelia(overlay: str, key: str) -> None:
    """#2419: no OIDC consumer carries an IdP URL nothing holds to the overlay's Authelia.

    A prod patch that drops one key falls back to the base, which is staging's IdP:
    prod then sends users to staging's login and the failure surfaces only there.
    """
    authelia, grafana = _authelia_and_grafana(overlay)
    portal = urlsplit(authelia["session"]["cookies"][0]["authelia_url"])
    url = urlsplit(grafana.get(key, ""))
    assert (url.scheme, url.netloc, url.path) == ("https", portal.netloc, OIDC_ENDPOINTS[key]), (
        f"{overlay}: {url.geturl()!r}"
    )


def test_the_dev_authelia_session_matches_the_overlays() -> None:
    """Authelia against Authelia: S1's bound is one number in every environment."""
    values = yaml.safe_load((ROOT / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    authelia = values["apps"]["services"]["security"]["authelia"]
    for overlay in OVERLAYS:
        session = _authelia_and_grafana(overlay)[0]["session"]
        assert (authelia["session_expiration"], authelia["session_inactivity"]) == (
            session["expiration"],
            session["inactivity"],
        ), f"common.yaml and {overlay} disagree on the session bound"


DEV_GRAFANA_COMPOSE = ROOT / "infra/stacks/services/observability/grafana/compose.base.yml"
DEV_GRAFANA_DERIVED = {
    "GF_AUTH_LOGIN_MAXIMUM_LIFETIME_DURATION": "${APPS_SERVICES_SECURITY_AUTHELIA_SESSION_EXPIRATION}",
    "GF_AUTH_LOGIN_MAXIMUM_INACTIVE_LIFETIME_DURATION": "${APPS_SERVICES_SECURITY_AUTHELIA_SESSION_INACTIVITY}",
    "GF_AUTH_SIGNOUT_REDIRECT_URL": (
        "https://${APPS_SERVICES_SECURITY_AUTHELIA_DOMAIN}/logout"
        "?rd=https%3A%2F%2F${APPS_SERVICES_OBSERVABILITY_GRAFANA_DOMAIN}%2F"
    ),
}


@pytest.mark.parametrize("key", sorted(DEV_GRAFANA_DERIVED))
def test_the_dev_compose_grafana_derives_the_bound_from_the_loader(key: str) -> None:
    """#2415: the dev Grafana runs on Grafana's 30d/7d defaults unless it carries these three.

    Each is a reference to a loader variable, never a literal, so the dev Authelia's
    numbers stay the only place the bound is written.
    """
    compose = yaml.safe_load(DEV_GRAFANA_COMPOSE.read_text(encoding="utf-8"))
    env = dict(item.split("=", 1) for item in compose["services"]["grafana"]["environment"] if isinstance(item, str))
    assert env.get(key) == DEV_GRAFANA_DERIVED[key]


def test_the_dev_compose_references_resolve_in_the_loader() -> None:
    """Every variable the dev Compose Grafana names is exported by the loader, as a duration or a host.

    Compose turns an unknown variable into an empty string, which Grafana reads as
    "unset" and falls back to 30d/7d: the bound would be gone while the reference
    strings above stay green. This resolves them the way the loader does.
    """
    values = ROOT / "infra/config/values"
    manager = ConfigurationManager("dev")
    merged = manager._deep_update(
        yaml.safe_load((values / "common.yaml").read_text(encoding="utf-8")),
        yaml.safe_load((values / "dev.yaml").read_text(encoding="utf-8")) or {},
    )
    exported = manager._flatten_dict(merged)
    names = {m for v in DEV_GRAFANA_DERIVED.values() for m in re.findall(r"\$\{(\w+)\}", v)}
    assert names, "no loader variable is referenced"
    for name in names:
        assert exported.get(name), f"{name} is not exported by the dev loader"
    for name in (
        "APPS_SERVICES_SECURITY_AUTHELIA_SESSION_EXPIRATION",
        "APPS_SERVICES_SECURITY_AUTHELIA_SESSION_INACTIVITY",
    ):
        assert re.fullmatch(r"\d+[smhd]", exported[name]), f"{name}={exported[name]!r} is not a Grafana duration"
