---
id: lesson-591-gitea-skips-its-sign-in-page-only-when-passkeys-are-off-too
type: lesson
status: active
created: "2026-10-17"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, oidc, sso]
---

# Gitea skips its sign-in page only when passkeys are off too

**Context**: With Authelia as Gitea's only OAuth2 source, every sign-in still
stopped on Gitea's own page with a "Sign in with Authelia" button: one click too
many for a single sign-on, and the same symptom the operator saw on n8n and
Grafana (#2390).

**Problem**: Gitea 1.27.3 redirects `/user/login` to the OAuth2 source on its
own (`performAutoLoginOAuth2` in `routers/web/auth/auth.go`) only when ALL hold:
exactly one OAuth2 source, the password form off, passkeys off, OpenID sign-in
off and SSPI off. `ENABLE_PASSWORD_SIGNIN_FORM` is the obvious one;
`ENABLE_PASSKEY_AUTHENTICATION` is the one that is easy to miss, and it also
defaults to `true`. With either left on, Gitea renders its page.

**Solution**: both set to `"false"` in the Beelink compose template
(`GITEA__service__*`). Measured after `make provision NODE=bee ENV=prod
TAGS=gitea`: `/user/login` answers `303` to `/user/oauth2/authelia`. API and git
basic auth is a separate key (`ENABLE_BASIC_AUTHENTICATION`, default `true`) and
stays on: the role's own password probe still got `200` from the API after the
restart, and the re-run reported `changed=0`.
`tests/test_gitea_signs_in_through_authelia.py` holds both halves.

**Rule**: to make an app hand its sign-in straight to the IdP, read the
condition in its source and switch off every competing method, not only the
password form. And check that the switch you flip does not also take away the
non-browser path break-glass uses: in Gitea the web form and API basic auth
are different keys.

**Tags**: `#gitea` `#sso` `#pr-2439`
