"""#1813: Argo CD's SSO session ends within Authelia's, and its sign-out goes through Authelia.

ADR-062 S2 and S3 for Argo CD, which runs native OIDC (no dex) against prod Authelia:

- S2. Argo CD keeps the IdP's ID token as its session and drops it at the token's
  expiry. It renews one only with a refresh token, used when `refreshTokenThreshold`
  is set and `offline_access` was granted. Neither is configured, so the session
  lasts one ID-token lifespan: Authelia's default, 1h, inside Authelia's own 8h.
  `users.session.duration` is not the bound here: it governs only tokens Argo CD
  signs itself (the local `admin` account), never an SSO session.
  So the bound holds as long as nobody adds a refresh path or raises the lifespan,
  and those three facts are what this test pins.
- S3. Signing out of Argo CD must end the Authelia session too, or the next
  "Log in via KubeLab IDP" comes straight back as the same user. Authelia 4.39 has no
  RP-initiated logout, so `logoutURL` is Authelia's `/logout` with an `rd` back to
  Argo CD. The `rd` is Argo CD's `/auth/login`, not its root: Argo CD 3.4 has no
  setting to skip its own login page, so a root `rd` lands on a "Log in via KubeLab
  IDP" button, while `/auth/login` starts the OIDC flow at once and the sign-out
  ends on Authelia's form. It also makes the round trip a test of S3: a session
  that survived the sign-out would come back signed in, with no form (#1813).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "infra/helm/argocd/values.yaml"
AUTHELIA = ROOT / "infra/k8s/overlays/prod/authelia-config"


def _cm() -> dict[str, Any]:
    return yaml.safe_load(VALUES.read_text(encoding="utf-8"))["configs"]["cm"]


def _oidc() -> dict[str, Any]:
    return yaml.safe_load(_cm()["oidc.config"])


def test_the_sign_out_ends_the_authelia_session_and_lands_on_its_sign_in_form() -> None:
    oidc = _oidc()
    logout = urlsplit(oidc["logoutURL"])
    assert f"{logout.scheme}://{logout.netloc}" == oidc["issuer"], "sign-out must reach the IdP Argo CD trusts"
    assert logout.path == "/logout"
    (rd,) = parse_qs(logout.query)["rd"]
    assert rd == f"{_cm()['url'].rstrip('/')}/auth/login", "a root rd stops on Argo CD's own login page"


def test_argo_cd_never_renews_an_sso_session_on_its_own() -> None:
    oidc = _oidc()
    assert "refreshTokenThreshold" not in oidc
    assert "offline_access" not in oidc["requestedScopes"]


def test_authelia_issues_argo_cd_no_refresh_token_and_keeps_the_default_lifespan() -> None:
    clients = yaml.safe_load((AUTHELIA / "oidc-clients.yml").read_text(encoding="utf-8"))
    (argocd,) = [c for c in clients["identity_providers"]["oidc"]["clients"] if c["client_id"] == "argocd"]
    assert "offline_access" not in argocd["scopes"]
    assert "refresh_token" not in argocd.get("grant_types", [])
    config = yaml.safe_load((AUTHELIA / "configuration.yml").read_text(encoding="utf-8"))
    assert "lifespans" not in config["identity_providers"]["oidc"], (
        "a custom lifespan can outlast the 8h session: check S2 before changing this"
    )
