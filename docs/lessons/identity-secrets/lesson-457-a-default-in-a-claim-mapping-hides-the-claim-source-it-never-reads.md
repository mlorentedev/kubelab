---
id: lesson-457-a-default-in-a-claim-mapping-hides-the-claim-source-it-never-reads
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, oidc, grafana, argocd, authelia]
---

# A default in a claim mapping hides the claim source it never reads, so the admin tier was never enforced

**Context**: The first run of `make auth-review ENV=prod` compared each app's live
privilege with the declared Authelia groups. It found `operator`, a member of
`admins`, as `Viewer` in Grafana. In Argo CD, User Info showed no groups at all.

**Problem**: Authelia 4.39 puts `groups` (and `preferred_username`) in UserInfo,
not in the ID token: its release notes call that the privacy-preserving default.
Two apps assumed the ID token:

- **Grafana** evaluates its role path on the ID token first, and moves on to
  UserInfo only when the result is empty. The path ended in `|| 'Viewer'`, so the
  ID token, which has no groups, already produced a valid answer, and UserInfo was
  never read. Every SSO user was Viewer. The login name worked through the same
  fallback, which is why nothing looked broken: `manu` was Admin only as the local
  break-glass account.
- **Argo CD** read groups from the ID token only, so `g, admins, role:admin`
  matched nobody and every SSO user fell to `policy.default: role:readonly`.

Configs and ADRs said the tier was enforced (#951 was counted as done on the
config), and nobody had measured it.

**Solution**: Grafana's path returns null when `groups` is absent
(`groups != null && (...) || null`), which sends it on to UserInfo. Argo CD sets
`enableUserInfoGroups` with a 5-minute cache, which also bounds how long a
changed group goes unseen. `tests/test_access_review.py` evaluates every role
path in the repo with a real JMESPath engine against an ID token with no groups.
`make auth-review` keeps measuring the live tier.

**Correction (2026-09-24, same day)**: the Grafana half of this diagnosis was
incomplete. The role-path defect was real, but it is not what produced the
measured `Viewer`. Through the public route Grafana never ran an OAuth login at
all: its auth proxy logged every user in from Authelia's `Remote-User` header,
and the proxy maps no role. Fixing the path changed nothing a user could see.
It took a real login after the fix to show it: the profile said "Synced via
Auth Proxy". See lesson-458. The Argo CD half stands, measured after deploy as
`argocd BOUNDED` with `admins` in User Info.

**Second correction (2026-09-24)**: the Grafana path itself was also wrong. Once
OAuth did run, `admins` still came out Viewer, because Grafana re-runs the path
on `{"groups": []}` when a source yields nothing, and `groups != null` answers
that with 'Viewer'. See lesson-461.

**Rule**: In a claim mapping evaluated over several sources in order, a default
turns "not here" into an answer and stops the search. Return empty when the
claim is missing, put the default where the last source is read, and verify the
tier by what a non-local admin can actually do, never by the config.

**Tags**: `#oidc` `#authelia-4.39` `#grafana` `#argocd` `#auth-004`
