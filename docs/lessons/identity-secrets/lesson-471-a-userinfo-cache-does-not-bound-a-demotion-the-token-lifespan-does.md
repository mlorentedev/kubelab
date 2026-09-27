---
id: lesson-471-a-userinfo-cache-does-not-bound-a-demotion-the-token-lifespan-does
type: lesson
status: active
created: "2026-09-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, argocd, authelia, oidc, rbac]
---

# A UserInfo cache does not bound a demotion: the token lifespan does

**Context**: AUTH-004 AC2 took the role account `operator` out of `admins` in
prod (#1853). Authelia restarted with the new users file at 02:03:28Z. Argo CD
reads `groups` from UserInfo (`enableUserInfoGroups`) with
`userInfoCacheExpiration: 5m`, and both the Helm values and `make auth-review`
stated that 5m as the bound on a changed group.

**Problem**: More than 10 minutes later, `operator`'s Argo CD User Info still
listed `admins`, and it could still Sync. At about 03:05 the same browser
session, with no manual login, showed `users` only. Authelia's log explains
the gap. Each Argo CD login leaves one `client_secret_basic` rejection, the
first try of the oauth2 auth-style autodetect. The marks were 02:02:56, just
before the restart, and 03:03:30, 1h00m34s later. That is the default token
lifespan. Argo CD requests no `offline_access`, so it has no refresh token, and
the expired session re-authenticated silently against the live Authelia SSO
session. When the 5m cache expires, Argo CD asks UserInfo again with the same
stored access token, and Authelia answers with the groups captured when that
token was issued. The cache controls how often Authelia is asked, not how
fresh the answer is.

**Solution**: The bound is stated as the token lifespan, 1h, in
`toolkit/features/access_review.py` (`ARGOCD_TOKEN_LIFESPAN`), in the Helm
comment and in CLAUDE.md. A test fails if either Authelia config sets
`lifespans`, or the argocd client names a `lifespan`, without the constant
following (#1861).

**Rule**: Before stating how long a revoked group stays effective in an OIDC
client, find which token the client presents when it re-reads the claims, and
how long the IdP lets that token answer with its original claims. A client-side
cache is only a lower bound. Measure a demotion by consequence, a refused
action at a known time after the change, never by reading the cache setting.

**Tags**: `#argocd` `#authelia` `#oidc` `#issue-1861`
