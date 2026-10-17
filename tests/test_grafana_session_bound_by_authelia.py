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
`session_*` values (the dev template does), so they are held to the same numbers.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

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


def test_the_dev_values_carry_the_same_bound() -> None:
    values = yaml.safe_load((ROOT / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    authelia = values["apps"]["services"]["security"]["authelia"]
    for overlay in OVERLAYS:
        session = _authelia_and_grafana(overlay)[0]["session"]
        assert (authelia["session_expiration"], authelia["session_inactivity"]) == (
            session["expiration"],
            session["inactivity"],
        ), f"common.yaml and {overlay} disagree on the session bound"
