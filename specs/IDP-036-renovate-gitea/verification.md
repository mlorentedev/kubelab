---
tags: [spec, verification, templates]
created: "2026-11-01"
---

# Verification - IDP-036-renovate-gitea

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] AC1 -> pending
- [ ] AC2 -> pending
- [ ] AC3 -> pending
- [x] AC4 -> `tests/test_renovate_engine_version.py`. The pin is `ci.renovate.image` in `common.yaml`; the workflow's `engine` step feeds `renovate-image` and `renovate-version`. `make mutate` RED for a literal `renovate-version` and for a wrong key. Renovate 44.199.2 `--dry-run=extract` reports `ghcr.io/renovatebot/renovate` 44.199.2 from the `common.yaml` image manager.
- [ ] AC5 -> pending
- [ ] AC6 -> pending
- [ ] AC7 -> pending

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- AC4: the pin sits under `ci` (CI / forge policy), not `apps.services`, which would make it a service with location and promotion axes and their gates.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/IDP-036-renovate-gitea/` -> `specs/archive/IDP-036-renovate-gitea/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
