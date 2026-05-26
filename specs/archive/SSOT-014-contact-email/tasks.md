---
tags: [spec, tasks, ssot, contact, email]
created: "2026-05-25"
---

# Tasks — SSOT-014-contact-email

## Setup

- [ ] Branch from master: `feat/ssot-014c-contact-email`
- [ ] `proposal.md` complete; AC testable
- [ ] Audit complete: 4 contact-email literals in common.yaml + downstream consumers (Ansible playbooks, generators)

## Implementation

- [ ] Add `apps.contact.email: mlorentedev@gmail.com` SSOT to `common.yaml`
- [ ] Add loader-injection logic in `toolkit/features/configuration.py:get_merged_config` after the deep_update phase:
      - `edge.traefik.acme_email` ← `apps.contact.email` if empty
      - `apps.services.observability.uptime_kuma.admin_email` ← same
      - Authelia users with `is_admin: true` and no `email`: fill with same
- [ ] Remove the 3 derived literals from `common.yaml` (`edge.traefik.acme_email`, `uptime_kuma.admin_email`, Authelia admin user email)
- [ ] Add a regression test in `tests/test_credentials_reconcile.py` or new file that asserts loader injection works (derived fields are populated from SSOT)
- [ ] Run `make config-generate ENV=staging`; verify `git diff infra/config/authelia/generated/staging/users_database.yml` empty
- [ ] Repeat for prod
- [ ] `make config-check-drift ENV={staging,prod}` green
- [ ] `make test` green

## Closing

- [ ] All 7 AC verified
- [ ] `verification.md` filled
- [ ] PR opened referencing `specs/SSOT-014-contact-email/` + closes SSOT-010
- [ ] Vault `11-tasks.md` SSOT-014c ticked + SSOT-010 ticked on merge
