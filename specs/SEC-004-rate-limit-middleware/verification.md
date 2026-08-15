---
tags: [spec, verification, templates]
created: "2026-08-14"
---

# Verification - SEC-004-rate-limit-middleware

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`
- [ ] Criterion 4 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **Pre-implementation investigation (2026-08-14) already produced one significant finding, captured here for continuity even though implementation hasn't started**: klipper-lb (K3s's built-in ServiceLB) MASQUERADEs every client's source IP before Traefik sees it, confirmed empirically in staging (temporary access log + `externalTrafficPolicy: Local` test, both reverted cleanly). This forced the scope from a per-client to a global rate limit and spawned a separate prerequisite issue (#1067) rather than silently narrowing this ticket. See `proposal.md` Risks section and #970's issue comments for full detail.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons.md`? Yes — already captured: "K3s's built-in ServiceLB masks every client's real IP — `externalTrafficPolicy: Local` cannot fix it" (`docs/lessons.md`, 2026-08-14, tags `#k3s #networking #servicelb #klipper-lb #sec-004 #gotcha`).
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
