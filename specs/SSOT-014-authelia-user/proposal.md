---
id: "SSOT-014-authelia-user"
type: spec
status: draft
created: "2026-05-25"
tags: [spec, proposal, ssot, authelia, identity]
template_version: "1.0"
---

# SSOT-014b: Authelia admin user auto-derives username from `apps.auth.admin_username`

<!-- from 10_projects/kubelab/11-tasks.md SSOT-014b: "Authelia user key auto-derive from apps.auth.admin_username. Remove duplicated apps.services.security.authelia.users.manu key. Update generator_authelia.py + _build_users_database in k8s_secrets.py." -->

## Why

`apps.auth.admin_username: manu` already declares the admin identity as the SSOT for the project. But the Authelia users list also hardcodes the same string as `apps.services.security.authelia.users[0].username: manu` — two declaration sites for the same fact. Any rename (Phase B SEC-PRIVACY-001) requires touching both. The duplication also forces a positional convention: "the entry whose username matches admin_username is the admin", which is brittle.

This sub-task (second of three in master plan SSOT-014) removes the duplication by adding an explicit `is_admin: true` marker and resolving username from the SSOT at generation time.

## What

The admin user entry in `common.yaml` declares its role via `is_admin: true` instead of hardcoding `username: manu`. Both code paths that consume the user list (`generator_authelia.py` for the Authelia config templates and `k8s_secrets.py:_build_users_database` for the K8s Secret) resolve the username as: `apps.auth.admin_username` when `is_admin` is true, else the explicit `user.username`.

Concrete output:
- `infra/config/authelia/generated/<env>/users_database.yml` regenerates byte-identical (key still `manu:` while admin_username is still `"manu"`).
- The K8s `authelia-users` Secret data `users_database.yml` is byte-identical.
- The downstream password hash lookup (`users_<username>_password_hash`) uses the resolved username, so renaming admin_username later (Phase B) automatically updates the hash key lookup path.

## Out of scope

- Renaming the value `"manu"` to anything else (Phase B / SEC-PRIVACY-001).
- Supporting multiple admin users. The schema allows it (any user with `is_admin: true` resolves to admin_username), but the current intent is one admin; a second `is_admin: true` would produce a duplicate key in the YAML output. The generators do not enforce uniqueness — relying on convention for now.
- Changing the SOPS hash key naming convention (`users_<username>_password_hash` stays).

## Risks / open questions

- **Two generators consuming the same list**: `generator_authelia.py` and `k8s_secrets.py:_build_users_database` both iterate `users`. The fix must apply identically in both — drift between them would surface as a runtime mismatch between Authelia's in-pod config (template path) and the K8s Secret (Python path). Mitigation: shared helper or carefully mirrored logic + drift gate test on the regenerated YAML.
- **SOPS hash key stability**: while `admin_username` stays `"manu"`, `users_manu_password_hash` continues to be the SOPS key. The Phase B value rename will require regenerating that SOPS entry. Not a blocker for this PR — flagged for Phase B planning.
- **Test fixtures**: `tests/test_credentials_reconcile.py` references `apps.authelia.users_manu_password_hash` directly in test data. Check whether that test asserts on the literal key or the resolved value. Update if needed.

## Acceptance criteria

- [ ] AC1: `apps.services.security.authelia.users[0]` in `common.yaml` has `is_admin: true` and no `username:` field.
- [ ] AC2: `git grep "username: manu" infra/config/values/common.yaml` returns 0 matches (down from 1).
- [ ] AC3: `apps.auth.admin_username: manu` remains the single declaration of the admin username string.
- [ ] AC4: `make config-generate ENV=staging` regenerates `infra/config/authelia/generated/staging/users_database.yml` byte-identical to the current file.
- [ ] AC5: Same as AC4 for `ENV=prod`.
- [ ] AC6: `make config-check-drift ENV={staging,prod}` green.
- [ ] AC7: `make test` green; if `test_credentials_reconcile.py` needed updating to read username via SSOT, it does so without changing semantics.

## References

- Vault: `10_projects/kubelab/11-tasks.md` SSOT-014b
- Sibling specs: SSOT-014-ssh-user (merged PR #218), SSOT-014-contact-email (next)
- Master plan: session memory `MEMORY.md` Session Handoff 2026-05-25
- Related: ADR-036 (shared infra namespace pattern, same SSOT discipline)
