"""AUTH-004 single door: Grafana signs users in through Authelia's OIDC only.

Measured 2026-09-24. With the auth proxy on, every request through the route
carried Authelia's `Remote-User` header and Grafana logged the user in from it,
before its login page rendered. The proxy maps no role, so `operator`, in
`admins`, was Viewer in both environments, and the OAuth role mapping never ran.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / "infra/k8s/base/services/grafana-config/grafana.env"
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())


def _env() -> dict[str, str]:
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key] = value
    return env


def _prod_overrides() -> dict[str, str]:
    for doc in yaml.safe_load_all((REPO / "infra/k8s/overlays/prod/patches.yaml").read_text()):
        if doc and doc.get("kind") == "ConfigMap" and doc["metadata"]["name"] == "grafana-config":
            return doc.get("data") or {}
    return {}


def test_the_only_interactive_login_is_oidc() -> None:
    env = _env()
    assert env["GF_AUTH_PROXY_ENABLED"] == "false", "the proxy logs users in from a header, with no role"
    assert env["GF_AUTH_GENERIC_OAUTH_ENABLED"] == "true"
    assert env["GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN"] == "true", "a login page with two doors is the incoherence"


def test_prod_does_not_reopen_the_proxy() -> None:
    """Prod patches the same object by name; a key there would win over the base."""
    assert not {k for k in _prod_overrides() if k.startswith("GF_AUTH_PROXY")}


def test_break_glass_opens_the_local_form_not_the_idp() -> None:
    """With auto-login, Grafana's root redirects to Authelia: exactly what is down
    when the break-glass path is in use."""
    decl = COMMON["apps"]["services"]["security"]["authelia"]["break_glass"]["grafana"]
    assert "disableAutoLogin=true" in decl.get("path", "")
