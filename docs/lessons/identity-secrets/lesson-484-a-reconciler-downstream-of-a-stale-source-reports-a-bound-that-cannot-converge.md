---
id: lesson-484-a-reconciler-downstream-of-a-stale-source-reports-a-bound-that-cannot-converge
type: lesson
status: active
created: "2026-09-29"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, authelia, grafana, auth-review, reconciliation]
---

# A reconciler downstream of a stale source reports a bound that cannot converge

**Context**: AUTH-011 moved `operator` from `admins` to `users`. `make auth-review`
compares each app's live tier with the declared groups and, with `APPLY=1`,
corrects it. For Grafana that means revoking the account's sessions, reported as
`bounded`: the role changes at the next login.

**Problem**: In staging, `operator` was still Grafana Admin after a fresh login.
`APPLY=1` revoked the sessions and reported `bounded`, and the next login wrote
Admin again. The role comes from the `groups` Authelia sends, and Authelia sent
`admins,users` (Loki: 122 `Check authorization of subject username=operator
groups=admins,users` lines in 30 minutes). Its users database is a Secret that
only `make apply-secrets` delivers. The merge had reached Argo CD, which reported
Synced, and never reached that Secret. The review judged every app against the
declaration and never judged the source the apps read from, so it reported a
bounded drift that no number of revokes could fix.

**Solution**: `make apply-secrets ENV=staging`, then one more login: Editor,
rc=0. Then #1911 (AUTH-014): the review reads the live `authelia-users` Secret
first and compares its groups with the rendered declaration, keeping only
usernames and groups in memory. A user whose groups lag is an `authelia` `drift`
naming `make apply-secrets ENV=<env>`, and is not corrected in any app, because
the app would write the old tier back at the next login.

**Rule**: Before a reconciler corrects a consumer, it checks the source that
consumer re-reads. A correction the consumer overwrites from a stale source
leaves the next reader of the report believing the drift will resolve. Judge
upstream first, and report downstream drift for that subject as blocked on the
upstream fix, never as bounded.

**Tags**: `#auth-review` `#authelia` `#issue-1911`
