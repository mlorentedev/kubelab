---
id: lesson-153-oidc-first-login-requires-account-linking
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, oidc, gitea, authelia, onboarding]
---

# OIDC first login requires account linking

**Context:** User logged in via Authelia OIDC to Gitea for the first time. Got "Sign In to Authorize Linked Account" page.

**Problem:** Not a bug — expected OIDC behavior. First login requires linking the external identity (Authelia) with a local account (Gitea). User enters local credentials once to establish the link.

**Solution:** Document this as expected first-login behavior. After linking, subsequent OIDC logins are automatic.

**Rule:** When onboarding users to OIDC, inform them about the one-time account linking step. Admin accounts created via postStart hook already exist — users link to them.
**Tags:** `#oidc` `#gitea` `#authelia` `#onboarding`
