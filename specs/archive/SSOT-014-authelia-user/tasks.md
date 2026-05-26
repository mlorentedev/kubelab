---
tags: [spec, tasks, ssot, authelia]
created: "2026-05-25"
---

# Tasks — SSOT-014-authelia-user

> TDD order. One task = one focused commit (or staged within one commit if mechanically tied).

## Setup

- [ ] Branch created from master: `feat/ssot-014b-authelia-user-derive`
- [ ] `proposal.md` complete; AC are testable
- [ ] Audit complete: only `generator_authelia.py` and `k8s_secrets.py:_build_users_database` iterate `authelia.users`

## Implementation

- [ ] Update `apps.services.security.authelia.users[0]` in `common.yaml`: add `is_admin: true`, remove `username: manu` (keep displayname, email, disabled, groups)
- [ ] Update `toolkit/features/generator_authelia.py` user iteration: `username = admin_username if user.get("is_admin") else user.get("username", "")`
- [ ] Update `toolkit/features/k8s_secrets.py:_build_users_database` user iteration: same resolution logic
- [ ] Regenerate Authelia config locally: `make config-generate ENV=staging`
- [ ] Verify `git diff infra/config/authelia/generated/staging/users_database.yml` is empty
- [ ] Repeat for `ENV=prod`
- [ ] Run `make test` — confirm `test_credentials_reconcile.py` either still passes or needs SSOT-aware update

## Closing

- [ ] All 7 AC from `proposal.md` verified
- [ ] `make config-check-drift ENV=staging` green
- [ ] `make config-check-drift ENV=prod` green
- [ ] `verification.md` filled with evidence
- [ ] PR opened referencing `specs/SSOT-014-authelia-user/`
- [ ] Vault `11-tasks.md` SSOT-014b ticked with PR link on merge
