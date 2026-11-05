---
id: lesson-709-a-redirect-regex-that-does-not-match-passes-the-request-through-silently
type: lesson
status: active
created: "2026-11-03"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls, traefik, argocd, auth]
---

# A redirect regex that does not match passes the request through, silently

**Context**: AUTH-020 (#2482) sends a browser that opens Argo CD at `/` with no `argocd.token` cookie to `/auth/login`, so it starts at Authelia instead of Argo CD's "Log in via" page. The rule is a Traefik router (`Path(/)` and a negated `HeaderRegexp` on `Cookie`) plus a `redirectRegex` Middleware. Before opening the PR, the matcher was measured on `traefik:v3.6` (3.6.25) with a stub backend.

**Problem**: The first Middleware anchored its regex on the root URL, `^https?://argo\.kubelab\.live/$`. The router matched `/?x=1` (its `Path` ignores the query), but the Middleware's regex did not, and Traefik does not treat that as an error: `redirectRegex` with no match calls the next handler. The request reached Argo CD and rendered the login page the rule exists to skip. Nothing logs it, and a test that only reads the manifest passes.

**Solution**: Make the router the only thing that decides. The Middleware's regex is `.*` and its replacement is the fixed sign-in URL, so every request the router hands it is redirected. `tests/test_argocd_sign_in_redirect.py` asserts that the regex matches `/` with and without a query string, and pins the router's shape. The measurement script ran 14 cases: cookie absent, other cookies only, `xargocd.token=`, a query string, the session cookie alone, after another cookie, split into `.1`, and in a second Cookie header, plus `/applications`, `/login`, `/auth/login`, `/api/version`, the webhook and a gRPC-web POST.

**Rule**: When a router already selects the requests, a `redirectRegex` behind it should match everything. A narrower regex creates a second selector, and its misses pass through without any sign. Prove the pair against the real image, query strings included, before trusting a test that only reads YAML.

**Tags**: `#traefik` `#argocd` `#auth-020`
