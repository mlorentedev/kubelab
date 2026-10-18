#!/usr/bin/env python3
"""AUTH-004 R1a probe — does an SSO login by a non-admin Authelia user
create a Gitea account while Gitea's own registration is disabled?

The password is resolved IN-PROCESS from the SOPS-merged config
(`apps.testing.authelia_test_password`), the same source the e2e suite uses. It is
never placed in an argument list, never exported to the environment (which
`/proc/<pid>/environ` would expose and every child would inherit) and never
printed. Nothing here emits a credential, a cookie value or a token: only URLs,
status codes and page titles, which is what the observation actually needs.

Usage:
    poetry run python3 r1a_sso_probe.py [env]
"""

from __future__ import annotations

import re
import sys

import httpx

from toolkit.features.configuration import ConfigurationManager

AUTHELIA = "https://auth.kubelab.live"
GITEA = "https://gitea.kubelab.live"
OAUTH_ENTRY = f"{GITEA}/user/oauth2/authelia"


def redact(url: str) -> str:
    """Strip query values that can carry a code/state/token."""
    return re.sub(r"(code|state|id_token|access_token)=[^&]+", r"\1=<redacted>", url)


def title_of(body: str) -> str:
    m = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
    return " ".join(m.group(1).split())[:160] if m else ""


def flash_of(body: str) -> str:
    """Gitea renders refusals in a flash div; grab whatever it says."""
    hits = re.findall(r'class="ui [^"]*(?:negative|error|warning)[^"]*message"[^>]*>(.*?)</div>', body, re.S | re.I)
    out = [" ".join(re.sub(r"<[^>]+>", " ", h).split())[:200] for h in hits]
    return " | ".join(out)


def main() -> int:
    env = sys.argv[1] if len(sys.argv) > 1 else "prod"
    merged = ConfigurationManager(env).get_merged_config()
    user = "testuser"
    password = merged.get("apps", {}).get("testing", {}).get("authelia_test_password")
    if not password:
        print(f"FATAL: apps.testing.authelia_test_password absent for env={env}", file=sys.stderr)
        return 2
    print(f"[setup] env={env} user={user} credential resolved in-process (not emitted)")

    with httpx.Client(follow_redirects=False, timeout=25.0, verify=True) as c:
        # --- 1. reachability, before anything else is interpretable -------
        for name, url in (("authelia", f"{AUTHELIA}/api/health"), ("gitea", f"{GITEA}/api/healthz")):
            try:
                r = c.get(url)
                print(f"[reach] {name:<8} {url} -> {r.status_code}")
            except Exception as exc:  # noqa: BLE001 - probe, report and continue
                print(f"[reach] {name:<8} {url} -> UNREACHABLE ({type(exc).__name__}: {exc})")

        # --- 2. first factor against Authelia -----------------------------
        r = c.post(
            f"{AUTHELIA}/api/firstfactor",
            json={"username": user, "password": password, "keepMeLoggedIn": False},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        print(f"\n[authelia] POST /api/firstfactor as '{user}' -> {r.status_code}")
        try:
            payload = r.json()
        except Exception:  # noqa: BLE001
            payload = {}
        print(f"[authelia] status field: {payload.get('status')!r}  message: {payload.get('message')!r}")
        session_present = any(k.lower().startswith("authelia") for k in c.cookies.keys())
        print(f"[authelia] session cookie acquired: {session_present}")
        if r.status_code != 200 or not session_present:
            print("\nRESULT: first factor did not succeed; the SSO leg was not attempted.")
            return 1

        # --- 3. walk Gitea's OIDC entry point by hand ---------------------
        print(f"\n[flow] GET {OAUTH_ENTRY}")
        url = OAUTH_ENTRY
        seen: list[str] = []
        final = None
        for hop in range(1, 16):
            resp = c.get(url, headers={"Accept": "text/html"})
            seen.append(f"  {hop:>2}. {resp.status_code} {redact(str(resp.url))}")
            loc = resp.headers.get("location")
            if resp.status_code in (301, 302, 303, 307, 308) and loc:
                url = str(httpx.URL(str(resp.url)).join(loc))
                continue
            final = resp
            break

        print("\n[flow] redirect chain:")
        print("\n".join(seen))

        if final is None:
            print("\nRESULT: redirect limit hit — chain did not terminate.")
            return 1

        body = final.text
        print(f"\n[final] {final.status_code} {redact(str(final.url))}")
        print(f"[final] title: {title_of(body)!r}")
        flash = flash_of(body)
        if flash:
            print(f"[final] flash:  {flash!r}")
        # Judge the session by what the PAGE proves, not by a cookie name: guessing the
        # name wrong yields a silent false negative, which is the same trap AC3's naive
        # assertion falls into. Cookie NAMES are printed (never values) so the real name
        # lands in the transcript as evidence rather than as anyone's recollection.
        signed_in = bool(re.search(r'href="/user/logout', body)) or bool(re.search(r'/user/settings"', body))
        print(f"[final] gitea session established: {signed_in}")
        print(f"[final] cookie names held (values never emitted): {sorted({ck.name for ck in c.cookies.jar})}")

        # --- 4. if Gitea parked on link_account, what does it actually offer? ---
        if "link_account" in str(final.url):
            forms = re.findall(r'<form[^>]*action="([^"]*)"[^>]*>', body, re.I)
            print(f"[link_account] form actions: {sorted(set(forms))}")
            offers_signup = bool(re.search(r'action="[^"]*link_account_signup', body, re.I))
            offers_signin = bool(re.search(r'action="[^"]*link_account_signin', body, re.I))
            print(f"[link_account] offers 'create new account' (signup): {offers_signup}")
            print(f"[link_account] offers 'link to existing'  (signin):  {offers_signin}")
            # Gitea hides the signup tab when registration is disabled; prove which
            # branch this instance took rather than inferring it from app.ini.
            note = re.findall(r"(register|registration)[^<]{0,120}", re.sub(r"<[^>]+>", " ", body), re.I)
            if note:
                print(f"[link_account] registration wording on page: {[' '.join(n.split())[:110] for n in note[:3]]}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
