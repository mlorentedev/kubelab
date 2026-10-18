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

No acceptance criterion was implemented, so none maps to a commit. The evidence for the abandonment
itself, as checked by the independent review on 2026-10-18:
- #2416 closed, #2446 and #2451 merged.
- `grep -rIl widget-proxy` finds no code, manifest or route outside specs and ADRs.
- `toolkit/features/k8s_middlewares.py` declares `MIDDLEWARE_CATALOG: list[MiddlewareSpec] = []`.

## Test status

- Test suite: not applicable, no code was written. `tests/test_homepage_retired.py` guards the
  premise that made this spec obsolete.
- No regressions: the archive changes only docs (this spec, ADR-034, ADR-035, CLAUDE.md).

## Decisions made during implementation

- Abandoned rather than rescoped: the server-side health check has no other consumer once the
  Homepage tiles are gone, and Uptime Kuma already probes the same services.

## Review dispositions

Review `review.md` (nan/deepseek-v4-flash, PASS-WITH-GAPS, reviewed `0556cbae`):

1. Template placeholders in Evidence, Test status and Decisions: applied, the sections above.
2. ADR-034 still lists `apps/widget-proxy` and a spec path that moves on archive: applied. The row
   is marked abandoned and the reference points at `specs/archive/_abandoned/`.
3. `tasks.md` names a `features.json` that does not exist: declined. The spec predates the
   `features.json` contract and was abandoned before implementation, so no feature list would ever
   be read. `tasks.md` is in the contract set, and a ticket for an archived spec would track nothing.
4. The checklist step aimed at the vault `11-tasks.md`: applied. Task state lives on the board
   (ADR-018), so the step now reads "close #465".
5. #465 still open: applied. It is closed as abandoned, with a pointer to #2416, once this merges.
6. "stays registered for them" in CLAUDE.md, left over from a two-item list: applied.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? no: abandoned before implementation; the reason above is the only record needed
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: ADR-035's anchored-decisions table records the change of status; no decision changes
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: abandoned before implementation

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: abandoned` (by `dotf spec archive --abandoned`)
- [x] Folder moved: `specs/DT-004-widget-proxy/` -> `specs/archive/_abandoned/DT-004-widget-proxy/`
- [ ] Tracking issue #465 closed as abandoned, pointing at #2416 (task state is on the board, ADR-018)
- [x] Promotions above executed (if any)
