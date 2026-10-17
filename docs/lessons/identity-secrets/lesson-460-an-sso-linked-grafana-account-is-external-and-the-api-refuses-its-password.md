---
id: lesson-460-an-sso-linked-grafana-account-is-external-and-the-api-refuses-its-password
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, grafana, oidc, break-glass]
---

# An SSO-linked Grafana account is external: the API refuses its password and its role

**Context**: #1825 made OIDC Grafana's only login. Grafana's break-glass account
was `manu`, its row id 1, per ADR-062 D4: one account with two auth paths, SSO
for daily use and a local password rotated by `secrets rotate --group break-glass`.
The access review corrected a drifted tier by editing the org role through the API.

**Problem**: The adversarial review failed #1825, and the Grafana 13.0.2 source
confirmed why. Once an SSO login links an account (a `user_auth` row whose module
is an enabled provider such as generic OAuth), Grafana treats it as external:

- **Password:** `errOnExternalUser` (`pkg/api/utils.go`) refuses both
  `PUT /api/user/password` and `PUT /api/admin/users/{id}/password`. The first SSO
  login of `manu` would have made the break-glass password unrotatable for good.
  The auth proxy's link never triggered this, because authproxy is not counted as
  an enabled provider, which is why rotation had worked.
- **Role:** an OAuth-synced role cannot be edited either
  (`ErrCannotChangeRoleForExternallySyncedUser`), so the review's `PATCH` of the
  org role would have been refused.
- **Password login still works:** `AuthenticatePassword` has no external guard.
  That is why a test of logging in would never have found this; only rotation fails.

Gitea is different: linking there leaves `LoginType` local, so D4 still holds for it.

**Solution**:
- **Break-glass:** Grafana gets a separate local account (#951, option A; ADR-062 D4
  amendment). Row id 1 is `breakglass`, with a login and email that no Authelia user
  has, so no SSO login can adopt it. `break_glass.py` refuses any collision. It must
  be renamed in each environment before OIDC becomes the only login there
  (`make grafana-admin-reconcile`), because the email-lookup migration flag would
  link a row that still carries `manu`'s email.
- **Tier:** for Grafana, the access review revokes the account's sessions
  (`POST /api/admin/users/{id}/logout`, which has no external guard) and reports
  `bounded`. The next request signs in again and takes the tier from `groups`.
  `skip_org_role_sync` would make the role editable again, but only by switching
  off the enforcement it exists for, so it is rejected.

**Rule**: Before you make an IdP the only way into an app, find out what the app
stops allowing on an account once the IdP has linked it, in the version you run:
password changes, role edits, deletion. Then check every automation that touches
those accounts (rotation, reconciliation, break-glass) against that list. An
emergency account must be one the IdP can never link, because anything the IdP
can take over fails exactly when the IdP is the problem.

**Tags**: `#grafana` `#oidc` `#break-glass` `#external-user` `#auth-004`
