#!/usr/bin/env python3
"""AUTH-004 R1 / AC4 probe — are Gitea's two signup POSTs honoured or refused?

R1a established that an SSO login parks at `/user/link_account`, and that Gitea
renders BOTH branches of that page even though `DISABLE_REGISTRATION = true`. A
rendered form proves nothing about whether its POST is honoured, and the
unauthenticated `/user/sign_up` page has the same shape: it says "Registration is
disabled" and still carries a `<form action="/user/sign_up">`.

Two POSTs settle it, and they answer different criteria:

  A. POST /user/link_account_signup, carrying a valid OIDC identity.
     -> Decides which of R1's two flag candidates implements AC3.
        Honoured: `ENABLE_AUTO_REGISTRATION=true` is enough (skip the page).
        Refused:  AC3 needs `DISABLE_REGISTRATION=false` +
                  `ALLOW_ONLY_EXTERNAL_REGISTRATION=true`, a far larger change.

  B. POST /user/sign_up, carrying no identity at all.
     -> Closes AC4 ("self-service registration remains closed"), demonstrated
        rather than read off `app.ini`.

Both may create an account. That is the point of running them, and the caller is
responsible for deleting whatever appears -- `gitea admin user list` before and
after is the control, exactly as in R1a.

The Authelia password is resolved IN-PROCESS from the SOPS-merged config; the
throwaway password for B is generated here and never leaves the process. Nothing
below emits a credential, a CSRF token or a cookie value: only URLs, status
codes, page titles and flash text.

Usage:
    poetry run python3 r1_signup_probe.py [env]
"""

from __future__ import annotations

import re
import secrets
import sys

import httpx

from toolkit.features.configuration import ConfigurationManager

AUTHELIA = "https://auth.kubelab.live"
GITEA = "https://gitea.kubelab.live"

# Anything this probe creates carries the name, so a leftover is unmistakable.
ANON_USER = "r1probe-anon-delete-me"

_SENSITIVE = ("_csrf", "password", "retype", "token")


def redact(url: str) -> str:
    return re.sub(r"(code|state|id_token|access_token)=[^&]+", r"\1=<redacted>", url)


def title_of(body: str) -> str:
    m = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
    return " ".join(m.group(1).split())[:140] if m else ""


def flash_of(body: str) -> str:
    hits = re.findall(r'class="ui [^"]*(?:negative|error|warning|positive)[^"]*message"[^>]*>(.*?)</div>', body, re.S | re.I)
    out = [" ".join(re.sub(r"<[^>]+>", " ", h).split())[:200] for h in hits]
    return " | ".join(h for h in out if h)


def form_fields(body: str, action: str) -> dict[str, str]:
    """Extract the inputs of the form whose action matches, so the POST carries
    what the page itself would send rather than what this script guesses."""
    m = re.search(rf'<form[^>]*action="{re.escape(action)}"[^>]*>(.*?)</form>', body, re.S | re.I)
    if not m:
        return {}
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input[^>]*>", m.group(1), re.I):
        name = re.search(r'name="([^"]*)"', tag, re.I)
        value = re.search(r'value="([^"]*)"', tag, re.I)
        if name:
            fields[name.group(1)] = value.group(1) if value else ""
    return fields


def show_fields(fields: dict[str, str]) -> dict[str, str]:
    return {k: ("<redacted>" if k in _SENSITIVE else v) for k, v in fields.items()}


def walk(c: httpx.Client, url: str, label: str) -> httpx.Response | None:
    """Follow redirects by hand so the chain is visible in the transcript."""
    for hop in range(1, 16):
        resp = c.get(url, headers={"Accept": "text/html"})
        print(f"  {label} {hop:>2}. {resp.status_code} {redact(str(resp.url))}")
        loc = resp.headers.get("location")
        if resp.status_code in (301, 302, 303, 307, 308) and loc:
            url = str(httpx.URL(str(resp.url)).join(loc))
            continue
        return resp
    return None


def report(tag: str, resp: httpx.Response, c: httpx.Client) -> None:
    body = resp.text
    print(f"  [{tag}] status : {resp.status_code}")
    print(f"  [{tag}] url    : {redact(str(resp.url))}")
    print(f"  [{tag}] title  : {title_of(body)!r}")
    flash = flash_of(body)
    if flash:
        print(f"  [{tag}] flash  : {flash!r}")
    # Judge a session by what the page proves, never by cookie presence:
    # Gitea sets `i_like_gitea` BEFORE authentication (R1a).
    signed_in = bool(re.search(r'href="/user/logout', body))
    print(f"  [{tag}] signed in: {signed_in}")
    print(f"  [{tag}] cookie names (values never emitted): {sorted({ck.name for ck in c.cookies.jar})}")


def probe_link_account_signup(env: str) -> None:
    print("=" * 78)
    print("A. POST /user/link_account_signup  — with a valid OIDC identity")
    print("   decides: which flag candidate implements AC3")
    print("=" * 78)

    merged = ConfigurationManager(env).get_merged_config()
    password = merged.get("apps", {}).get("testing", {}).get("authelia_test_password")
    if not password:
        print("FATAL: apps.testing.authelia_test_password absent", file=sys.stderr)
        return

    with httpx.Client(follow_redirects=False, timeout=25.0) as c:
        r = c.post(
            f"{AUTHELIA}/api/firstfactor",
            json={"username": "testuser", "password": password, "keepMeLoggedIn": False},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        print(f"  [authelia] firstfactor as 'testuser' -> {r.status_code}")
        if r.status_code != 200:
            print("  aborting: first factor failed")
            return

        page = walk(c, f"{GITEA}/user/oauth2/authelia", "sso")
        if page is None or "link_account" not in str(page.url):
            print(f"  aborting: expected link_account, got {page and redact(str(page.url))}")
            return

        fields = form_fields(page.text, "/user/link_account_signup")
        if not fields:
            print("  aborting: signup form not found on the page")
            return
        print(f"  form fields as the page would send them: {show_fields(fields)}")

        # The template ships this form as an EMPTY SHELL when registration is
        # disabled: a CSRF token plus the sentence "Registration is disabled".
        # Posting it as-is therefore measures the template, not the gate. Inject
        # the fields the template withholds so the HANDLER is what answers --
        # presentation that hides a control and a handler that refuses one are
        # different security properties, and only the second is enforcement.
        fields.setdefault("user_name", "r1probe-sso-delete-me")
        fields.setdefault("email", "r1probe-sso-delete-me@kubelab.test")
        print(f"  fields actually posted (handler under test): {show_fields(fields)}")

        resp = c.post(
            f"{GITEA}/user/link_account_signup",
            data=fields,
            headers={"Referer": str(page.url), "Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
            nxt = str(httpx.URL(str(resp.url)).join(resp.headers["location"]))
            print(f"  post -> {resp.status_code}, following to {redact(nxt)}")
            follow = walk(c, nxt, "post")
            if follow is not None:
                resp = follow
        report("A", resp, c)


def probe_anonymous_signup() -> None:
    print()
    print("=" * 78)
    print("B. POST /user/sign_up  — no identity at all")
    print("   decides: AC4, self-service registration stays closed")
    print("=" * 78)

    with httpx.Client(follow_redirects=False, timeout=25.0) as c:
        page = c.get(f"{GITEA}/user/sign_up", headers={"Accept": "text/html"})
        print(f"  [get] {page.status_code} {page.url}  title={title_of(page.text)!r}")

        fields = form_fields(page.text, "/user/sign_up")
        if not fields:
            print("  no sign_up form on the page — nothing to POST, AC4 satisfied at the form layer")
            return

        throwaway = secrets.token_urlsafe(18)
        fields.update(
            {
                "user_name": ANON_USER,
                "email": f"{ANON_USER}@kubelab.test",
                "password": throwaway,
                "retype": throwaway,
            }
        )
        print(f"  form fields (generated password never emitted): {show_fields(fields)}")

        resp = c.post(
            f"{GITEA}/user/sign_up",
            data=fields,
            headers={"Referer": f"{GITEA}/user/sign_up", "Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
            nxt = str(httpx.URL(str(resp.url)).join(resp.headers["location"]))
            print(f"  post -> {resp.status_code}, following to {redact(nxt)}")
            follow = walk(c, nxt, "post")
            if follow is not None:
                resp = follow
        report("B", resp, c)


def main() -> int:
    env = sys.argv[1] if len(sys.argv) > 1 else "prod"
    print(f"env={env}; credentials resolved in-process, never emitted\n")
    probe_link_account_signup(env)
    probe_anonymous_signup()
    print()
    print("Now run `gitea admin user list` again. Delete anything this created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
