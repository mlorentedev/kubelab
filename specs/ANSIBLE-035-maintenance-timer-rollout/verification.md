---
tags: [spec, verification, templates]
created: "2026-08-14"
---

# Verification - ANSIBLE-035-maintenance-timer-rollout

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] AC1 (gate vars) -> commit `<hash>`
- [ ] AC2 (7 playbooks include the role) -> commit `<hash>`
- [ ] AC3 (`maintain.yml` unaffected) -> `--list-tasks` diff, before/after
- [ ] AC4 (live per-node rollout + idempotence, aws1 convergence) -> per-node `systemctl list-timers` output + second-run recap, one row per node
- [ ] AC5 (OnFailure notify wiring) -> commit `<hash>`
- [ ] AC6 (notify path proven live, twice) -> delivery evidence + failure-injection evidence
- [ ] AC7 (rotate_note updated) -> commit `<hash>`
- [ ] Runbook criterion -> `docs/runbooks/<file>.md`

## Test status

- Unit/lint/type: `<command> -> <output>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- Notify design initially assumed a direct Apprise integration; corrected after finding `apprise.yaml` is cluster-internal-only. Real integration point is n8n's public webhook — see proposal.md's Risks section for the full correction.
- All 7 nodes notify to prod n8n regardless of their own `deploy_env`, to avoid the alert path depending on ace1 (staging n8n's host) being powered on — user-confirmed design choice.
- `webhook_secret`'s prod value relocated from `prod.enc.yaml` to `common.enc.yaml`, following the existing aws1/hub-creds precedent, so no playbook needs a new secrets-decrypt task.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-035-maintenance-timer-rollout/` -> `specs/archive/ANSIBLE-035-maintenance-timer-rollout/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
