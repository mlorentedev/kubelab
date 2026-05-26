---
id: "SSOT-014-contact-email"
type: spec
status: archived
created: "2026-05-25"
tags: [spec, proposal, ssot, contact, email]
template_version: "1.0"
---

# SSOT-014c: Operator contact email as single source of truth

<!-- from 10_projects/kubelab/11-tasks.md SSOT-014c: "Consolidate contact email — new SSOT apps.contact.email. Derive infra.smtp.user, acme_email, Authelia user email, Authelia notifier sender. Closes SSOT-010 also." -->

## Why

The operator contact email (`mlorentedev@gmail.com`) appears in 4 different paths in `common.yaml` today:
- `edge.traefik.acme_email` (Let's Encrypt account email)
- `apps.services.observability.uptime_kuma.admin_email` (incident alert recipient)
- `apps.services.security.authelia.users[0].email` (admin user identity email)
- `infra.smtp.user` (SMTP relay account, post-SSOT-012)

A future rename ("manu" → generic) requires editing 4 lines that must stay in lockstep. This is master plan SSOT-014's third sub-task — establishes a single SSOT (`apps.contact.email`) and derives the operator-contact paths from it.

**Scope decision (user-approved 2026-05-25):** derive ONLY operator-contact fields (acme_email, uptime_kuma admin_email, Authelia admin user email). Do **NOT** derive `infra.smtp.user` — semantic distinction: SMTP relay account *could* be a separate `noreply@kubelab.live` in the future; coupling it to operator contact would force a refactor when that day comes.

## What

New SSOT field `apps.contact.email: mlorentedev@gmail.com` in `common.yaml`. The toolkit configuration loader (`toolkit/features/configuration.py:get_merged_config`) post-processes the loaded config to fill in derived fields if they are empty/absent:

- `edge.traefik.acme_email` ← `apps.contact.email` (if not set)
- `apps.services.observability.uptime_kuma.admin_email` ← `apps.contact.email` (if not set)
- For each Authelia user with `is_admin: true` and no explicit `email` field: `email` ← `apps.contact.email`

The literal `mlorentedev@gmail.com` is removed from those four paths in `common.yaml`. Consumers (Ansible playbooks, generators, Python CLI code) read the same paths as before — they receive the resolved value at load time without code changes.

## Out of scope

- `infra.smtp.user` coupling (scope decision above).
- K8s manifests with hardcoded email (`infra/k8s/base/services/authelia.yaml` notifier block, `infra/k8s/overlays/prod/patches.yaml` SMTP override). These are static, non-generated manifests — refactoring them to derive from SSOT requires moving them into the generator output set. Separate concern; leaves SSOT-010 partially open for that residual.
- Phase B value rename ("mlorentedev@gmail.com" → "kubelab@…"). Trivial 1-line follow-up after this PR.

## Risks / open questions

- **"Magic" injection in the config loader**: a reader of `common.yaml` may not see why `edge.traefik.acme_email` is non-empty at runtime when removed from file. Mitigation: comment in `common.yaml` at `apps.contact.email` explaining the derivation; comment in `configuration.py:get_merged_config` listing exactly which fields are filled. **Status:** accepted as documented trade-off.
- **Drift gate must catch unintended changes**: regenerated ConfigMaps + Authelia configs must be byte-identical. Verified locally before commit.
- **Authelia admin user email vs admin_username pattern**: SSOT-014b already established `is_admin: true` resolves to `apps.auth.admin_username` for the user key. This PR extends the same admin-user-marker pattern to derive the email field too. Consistent with prior sub-task.

## Acceptance criteria

- [ ] AC1: `apps.contact.email: mlorentedev@gmail.com` declared in `common.yaml`; the 3 derived fields (`edge.traefik.acme_email`, `uptime_kuma.admin_email`, Authelia admin user email) have their literal removed.
- [ ] AC2: `git grep "mlorentedev@gmail.com" infra/config/values/common.yaml | wc -l` == **2** (down from 4) — the two remaining declarations are `apps.contact.email` (operator-contact SSOT, this spec) and `infra.smtp.user` (SMTP relay account, intentionally separate SSOT per scope decision; per ADR-036 distinction).
- [ ] AC3: `make config-generate ENV=staging` produces `infra/config/authelia/generated/staging/users_database.yml` byte-identical to committed.
- [ ] AC4: Same for `ENV=prod`.
- [ ] AC5: `make config-check-drift ENV={staging,prod}` green.
- [ ] AC6: `make test` green; loader injection covered by new test asserting derived fields are populated when only `apps.contact.email` is set.
- [ ] AC7: Ansible playbooks that reference `config.edge.traefik.acme_email` continue to receive the correct value (no playbook change needed). Verified by playbook syntax check (`ansible-playbook --syntax-check`) or by inspecting regenerated output.

## References

- Vault: `10_projects/kubelab/11-tasks.md` SSOT-014c (closes SSOT-010 partial)
- Sibling specs: SSOT-014-ssh-user (PR #218 merged), SSOT-014-authelia-user (PR #219 merged)
- Master plan: session memory `MEMORY.md` Session Handoff 2026-05-25
- ADR-036 (shared infra namespace pattern; SSOT-014c follows the same SSOT discipline)
- Phase B follow-up: SEC-PRIVACY-001 trivial value rename once this lands
