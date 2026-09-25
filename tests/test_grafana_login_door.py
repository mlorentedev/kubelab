"""AUTH-004 single door: Grafana signs users in through Authelia's OIDC only.

Measured 2026-09-24. With the auth proxy on, every request through the route
carried Authelia's `Remote-User` header and Grafana logged the user in from it,
before its login page rendered. The proxy maps no role, so `operator`, in
`admins`, was Viewer in both environments, and the OAuth role mapping never ran.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
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


def _rendered(overlay: str) -> dict[str, str]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    for doc in yaml.safe_load_all(out.stdout):
        if doc and doc.get("kind") == "ConfigMap" and doc["metadata"]["name"].startswith("grafana-config-"):
            return doc["data"]
    raise AssertionError(f"no grafana-config ConfigMap in the {overlay} overlay")


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_each_environment_renders_one_door(overlay: str) -> None:
    """Read from what each overlay renders, not from the base file: a prod patch that
    set any of these back would pass every check of the source."""
    env = _rendered(overlay)
    assert env.get("GF_AUTH_PROXY_ENABLED") == "false"
    assert env.get("GF_AUTH_GENERIC_OAUTH_ENABLED") == "true"
    assert env.get("GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN") == "true"


def test_break_glass_opens_the_local_form_not_the_idp() -> None:
    """With auto-login, Grafana's root redirects to Authelia: exactly what is down
    when the break-glass path is in use."""
    decl = COMMON["apps"]["services"]["security"]["authelia"]["break_glass"]["grafana"]
    assert "disableAutoLogin=true" in decl.get("path", "")
