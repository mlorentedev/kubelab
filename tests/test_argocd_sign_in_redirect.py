"""AUTH-020 (#2482): an anonymous browser opening Argo CD starts at Authelia, not at "Log in via".

Argo CD v3.4.1 always renders its own login page, and `/auth/login` answers 303 to Authelia.
So the edge sends a request for `/` that carries no `argocd.token` cookie to `/auth/login`.
Everything else reaches Argo CD untouched: the CLI (Bearer, gRPC-web), `/api/webhook`, the
SPA's own paths, and any request that already holds a session.

Measured on traefik:v3.6 (3.6.25, 2026-11-03) with the rule below and a stub backend: `/` with
no cookie, with only other cookies, with `xargocd.token=` and with a query string got 302 to
`/auth/login`; `/` with `argocd.token` (alone, after another cookie, split into `.1`, or in a
second Cookie header) and `/applications`, `/login`, `/auth/login`, `/api/version`,
POST `/api/webhook` and a gRPC-web POST reached the backend. A first `redirectRegex` anchored on
`/$` let `/?x=1` through unredirected, which is why the regex now matches anything: the router,
not the middleware, decides which requests are redirected. This file pins that shape; the
routing itself was proven against the real image.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
HOST = "argo.kubelab.live"
SIGN_IN = f"https://{HOST}/auth/login"


@pytest.fixture(scope="module")
def prod() -> list[dict]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays/prod")], capture_output=True, text=True, encoding="utf-8"
    )
    assert out.returncode == 0, out.stderr
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def _routes(prod: list[dict]) -> list[dict]:
    route = next(d for d in prod if d["kind"] == "IngressRoute" and d["metadata"]["name"] == "argocd")
    return route["spec"]["routes"]


def _redirect(prod: list[dict]) -> dict:
    redirects = [r for r in _routes(prod) if "Cookie" in r["match"]]
    assert len(redirects) == 1, "exactly one Argo CD rule redirects to sign-in"
    return redirects[0]


def _cookie_regexp(prod: list[dict]) -> str:
    found = re.search(r"&& !HeaderRegexp\(`Cookie`, `([^`]+)`\)", _redirect(prod)["match"])
    assert found, "the redirect must apply only to requests WITHOUT an Argo CD session cookie"
    return found.group(1)


def test_only_the_root_path_is_redirected(prod: list[dict]) -> None:
    match = _redirect(prod)["match"]
    assert f"Host(`{HOST}`)" in match
    assert "Path(`/`)" in match
    assert "PathPrefix" not in match, "a prefix would catch the CLI, the API and the webhook"


@pytest.mark.parametrize(
    "cookie",
    ["argocd.token=x", "a=1; argocd.token=x", "argocd.token=x; argocd.token.1=y", "a=1;argocd.token=x"],
)
def test_a_session_cookie_skips_the_redirect(prod: list[dict], cookie: str) -> None:
    assert re.search(_cookie_regexp(prod), cookie)


@pytest.mark.parametrize("cookie", ["", "other=1", "xargocd.token=x", "authelia_session=s"])
def test_no_session_cookie_is_redirected(prod: list[dict], cookie: str) -> None:
    assert not re.search(_cookie_regexp(prod), cookie)


def test_the_redirect_outranks_the_passthrough_and_keeps_every_guard(prod: list[dict]) -> None:
    redirect = _redirect(prod)
    passthrough = [r for r in _routes(prod) if r is not redirect]
    assert len(passthrough) == 1
    assert redirect["priority"] > passthrough[0].get("priority", 0)
    guards = {"secure-headers", "rate-limit", "crowdsec-bouncer"}
    assert guards <= {m["name"] for m in redirect["middlewares"]}
    assert guards <= {m["name"] for m in passthrough[0]["middlewares"]}


def test_the_redirect_goes_to_argo_cds_own_sign_in_and_is_temporary(prod: list[dict]) -> None:
    names = {m["name"] for m in _redirect(prod)["middlewares"]}
    middlewares = [d for d in prod if d["kind"] == "Middleware" and d["metadata"]["name"] in names]
    redirects = [m["spec"]["redirectRegex"] for m in middlewares if "redirectRegex" in m["spec"]]
    assert len(redirects) == 1, "the redirect Middleware must render with the overlay"
    spec = redirects[0]
    assert spec["replacement"] == SIGN_IN
    assert not spec.get("permanent", False), "a 301 would be cached and outlive a sign-in"
    for url in (f"https://{HOST}/", f"https://{HOST}/?x=1"):
        assert re.search(spec["regex"], url), f"{url} would pass the router and miss the redirect"
