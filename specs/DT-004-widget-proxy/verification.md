---
tags: [spec, verification, templates]
created: "2026-05-13"
---

# Verification - DT-004-widget-proxy

## Abandoned

Abandoned 2026-10-18 (kubelab#2443): the premise is gone. The spec existed to give the Homepage
cockpit's tiles a server-side health check instead of browser `fetch(no-cors)`. On 2026-10-17 the
operator retired `home.kubelab.live` entirely (#2416):
- #2446 removed the deployment, generator, DNS record, monitor and break-glass entry.
- #2451 removed the tile fields.
- `tests/test_homepage_retired.py` keeps them from returning.

Nothing was built: no `apps/widget-proxy`, no `MIDDLEWARE_CATALOG` entry. The only ticked tasks are
the two spec-writing ones. ADR-034's language decision stands on its own, and ADR-035's Stage 1
plugin stays registered for its remaining anchor, Pollex public (AI-004).

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? no: abandoned before implementation; the reason above is the only record needed
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: ADR-035's anchored-decisions table records the change of status; no decision changes
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: abandoned before implementation

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/DT-004-widget-proxy/` -> `specs/archive/DT-004-widget-proxy/`
- [ ] Backlog entry in vault `11-tasks.md` ticked with PR link
- [ ] Promotions above executed (if any)
