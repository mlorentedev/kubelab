---
id: "AUTH-014-idp-groups-drift"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-09-29"
issue: "mlorentedev/kubelab#1911"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# AUTH-014-idp-groups-drift

## Why

A change to a user's `groups` in `common.yaml` merges and Argo CD reports Synced, but
Authelia keeps serving the old groups: they reach it inside the `authelia-users`
Secret, which only `make apply-secrets ENV=<env>` delivers (#1911). `make auth-review`
compares each app's live tier with the declaration, never the identity provider's
live groups, so the upstream lag looks like an app drift. Measured 2026-09-29 in
staging: Grafana `operator declared=Editor live=Admin`, `APPLY=1` revoked the sessions
and reported `bounded`, and the next login wrote Admin again. It reported a drift
that could never converge.

## What

`make auth-review ENV=<env>` reads the live `authelia-users` Secret in the env's spoke
and compares each user's `groups` with the declaration, keeping only usernames and
groups in memory. Any difference (other groups, a declared user missing, a live user
not declared) is an `authelia` finding with status `drift` whose detail names
`make apply-secrets ENV=<env>`, so the command exits 1. For a user whose live groups
lag, the review does not correct that user in any app, even under `APPLY=1`: an edit
or a revoke is undone at the next login, from the stale groups. It reports that
user's app drift as `drift`, naming the same command, never `bounded` or `fixed`.

## Out of scope

- Running `apply-secrets` from the review. It restarts Authelia, and the operator decides when.
- Delivering Secrets by GitOps, which is ADR-038's deferred decision (#1613).
- Folding the Argo CD RBAC evaluator into the review (#1876, AUTH-012).

## Risks / open questions

- The Secret carries argon2 password hashes. Mitigation: it is decoded and parsed
  in-process, only `groups` is kept, and a test feeds a database with a hash and
  asserts that no finding field and no log line contains it.
- The spoke may be unreachable (staging is on-demand). An unreadable Secret is an
  `authelia` `failed` finding, as an unreadable app already is, and the app review
  proceeds as today.

## Acceptance criteria

- [ ] AC1: a live users database whose groups differ from the declaration, or that lacks or adds a user, yields an `authelia` `drift` finding naming `make apply-secrets ENV=<env>`; an equal one yields `ok`.
- [ ] AC2: for a user whose live groups lag, `APPLY=1` edits and revokes nothing for that user in any app, and reports that user's app drift as `drift` naming the same command.
- [ ] AC3: no password hash from the users database reaches a finding or the log.
- [ ] AC4: an unreadable Secret is an `authelia` `failed` finding, and the command exits 1.
- [ ] AC5: live, `make auth-review ENV=prod` and `ENV=staging` report `authelia ... ok` and exit 0.

## References

- Issue #1911. Evidence: AUTH-011 `specs/archive/AUTH-011-operator-tier/verification.md` (the staging correction).
- ADR-062 D2 (tiers), ADR-038 and #1613 (automatic delivery).
- Runbook `docs/runbooks/identity-tier-change.md`, which names this gap.
