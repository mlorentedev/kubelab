---
id: lesson-459-grafana-oauth-never-finds-an-existing-account-by-login
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, grafana, oidc, migration]
---

# Grafana OAuth never finds an existing account by login, so switching an account to OAuth fails with "user sync failed"

**Context**: To move Grafana from the auth proxy to OAuth (lesson-458), `operator`
opened `/login/generic_oauth` in staging. The browser said "Login failed: user
sync failed". Loki had the cause:
`user.sync: Failed to create user error="user not found" auth_module=oauth_generic_oauth`.

**Problem**: In Grafana 13.0.2 (`pkg/services/authn/clients/oauth.go`), generic
OAuth finds a returning user in only two ways:

- by the OAuth link (`user_auth` row, keyed by the IdP's `sub`) stored at signup;
- by email, and only when `[auth] oauth_allow_insecure_email_lookup = true`.

It **never** looks up by login. `operator` had been created by the auth proxy and
had no OAuth link, so the lookup found nothing. Grafana then tried to create the
account, hit the existing login, and re-read it. The re-read also found nothing,
and the error Grafana logged was that last "not found"
(`authn/authnimpl/sync/user_sync.go`), which hides the collision behind it.
Separately, `token is not in JWT format: authelia_at_...` is noise: Authelia
issues opaque access tokens, and Grafana reads the claims from UserInfo instead.

**Solution**: `GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP=true`, as a migration
step. The first OAuth login finds the account by email, and
`updateUserAttributes` stores the missing link (`needsConnectionCreation :=
userAuth == nil`). Every later login uses the link. The flag is safe here while
it is on: Authelia's users file is declared by the operator, no user can change
their own email, and CI requires every identity to have a distinct one. It is
still a migration flag. Remove it once every account shows the OAuth label.
Deleting the proxy-created accounts would lose their state, and account 1 is the
break-glass admin. Writing `user_auth` rows by hand is a manual operation on a
live system.

**Rule**: Before you switch an app's login mechanism, find out which keys the new
mechanism uses to match an existing account, in the version you run. Login name,
email and subject are not interchangeable, and an app that matches on none of the
ones your accounts carry answers by trying to create a duplicate. Treat the
bridge setting as temporary: check that each account has adopted the new
mechanism, then take the setting out.

**Tags**: `#grafana` `#oidc` `#migration` `#user-sync` `#auth-004`
