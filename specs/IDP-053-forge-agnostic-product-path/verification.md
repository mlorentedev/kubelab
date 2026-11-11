---
tags: [spec, verification]
created: "2026-11-03"
id: "IDP-053-forge-agnostic-product-path"
type: spec-verification
status: active
owner: manu
---

# Verification - IDP-053-forge-agnostic-product-path

Spec-only so far: nothing below is proven yet. Each row is filled by the slice that settles it.

## Evidence

- [ ] AC1 (S1a) -> commit `<hash>` / `tests/test_product_registry.py`, `tests/test_registry_prune.py`
- [ ] AC2 (S1b) -> commit `<hash>` / `tests/test_promotion.py`, `tests/test_prod_images_always_on.py`
- [ ] AC3 (S2a, S2b) -> commit `<hash>` / `tests/test_image_pull_secret.py`
- [ ] AC4 (S2c) -> commit `<hash>` / `tests/test_gitea_registry_pull_token.py`; deployed: `registry-check` output
- [ ] AC5 (S3a) -> commit `<hash>` / the eight test files named in `tasks.md`
- [ ] AC6 (S3b) -> commit `<hash>` / `make test` output
- [ ] AC7 (S4) -> deploy PR `<number>`; `kubectl` and `curl` output
- [ ] AC8 (S5) -> commit `<hash>` / `tests/test_forge_adapter.py`; S5b API note: `docs/lessons/toolkit-tooling/lesson-733-gitea-answers-an-ambiguous-short-sha-with-the-same-404-as-an-unknown-one.md` (S5c's token test still open)
- [ ] AC9 (S6) -> commit `<hash>` / workflow tests; dry-run run URL
- [ ] AC10 (S7) -> comment URL on #2612; runbook line
- [ ] AC11 (S8) -> commit `<hash>` / `tests/test_registry_digest.py`
- [ ] AC12 (S9) -> commit `<hash>` / `tests/test_deploy_shape.py`

## Test status

- Test suite: `<command> -> <output>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no

## Decisions made during implementation

D1 and D2 in `proposal.md` are open; record the owner's rulings here with the date.

## Promotion candidates

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason> (D5 `events.prod` as the prod-lane declaration and D6 per-host pull Secrets are candidates for an ADR-067 amendment)
- [ ] New pattern candidate for `00_meta/patterns/`? <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/IDP-053-forge-agnostic-product-path/` -> `specs/archive/IDP-053-forge-agnostic-product-path/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
