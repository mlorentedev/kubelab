---
id: lesson-520-open-webui-login-form-flag-hides-the-form-only
type: lesson
status: active
created: "2026-10-03"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, open-webui, oidc, authelia, break-glass]
---

# Open WebUI's `ENABLE_LOGIN_FORM=false` hides the form; the password endpoint stays open

**Context**: AI-009 PR 1b connects Open WebUI v0.11.4 on ace2 to prod Authelia.
The spec planned `ENABLE_LOGIN_FORM=false` so Authelia would be the only door,
which left the break-glass question open. Before deciding, the pinned source was
read rather than the documentation.

**Problem**: Three Open WebUI behaviours that each looked like configuration were not:

1. `ENABLE_LOGIN_FORM` is a UI setting (`ui.enable_login_form`). `POST
   /api/v1/auths/signin` is gated only by `ENABLE_PASSWORD_AUTH`, which defaults
   to true (`backend/open_webui/routers/auths.py:724`). With the form hidden,
   any account with a password still signs in through the API. The "single door"
   never existed.
2. With the form on and an empty database, the first signup is accepted even
   with `ENABLE_SIGNUP=false` (`auths.py:911`, "Don't gate the first admin on
   ENABLE_SIGNUP"), and it becomes admin.
3. Open WebUI calls UserInfo only when the ID token lacks the email claim or the
   username claim (`utils/oauth.py:1927`; the username claim defaults to `name`).
   Authelia 4.39 sends `groups` only in UserInfo (lesson-457). If the ID token
   carries both claims, role management never sees a group, and every login
   lands on the default role.

A fourth is general: with `ENABLE_PERSISTENT_CONFIG` on (the default), most env
values are read once into the database, so a later Ansible edit applies cleanly
and changes nothing.

**Solution**: The form stays on as the break-glass door, and nobody can sign up
through it. A local account `breakglass` is seeded by `WEBUI_ADMIN_EMAIL` and
`WEBUI_ADMIN_PASSWORD`, which run on an empty database before the first request
is served (`main.py:376`). The role refuses to start Open WebUI without that
password, and after every start it signs in as `breakglass` and fails unless the
answer says `role: admin`. `OAUTH_USERNAME_CLAIM=preferred_username` names a
claim Authelia keeps out of the ID token, so UserInfo is always read.
`ENABLE_PERSISTENT_CONFIG=false` makes the env file the configuration of record.

**Rule**: Before using an app flag as a security boundary, find the code path it
actually gates. "Disable the login form" and "disable password authentication"
are different switches in more than one app. And for an app that copies its env
into its database, either turn persistence off or treat every env change as a
migration.

**Tags**: `#open-webui` `#oidc` `#break-glass` `#ai-009`
