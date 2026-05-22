---
tags: [spec, verification]
created: "2026-05-13"
updated: "2026-05-21"
---

# Verification - AI-002-e2e-tests

> Skeleton — fill at implementation time (AI-002 cannot start until AI-001 PR-C merges and the prod Ollama endpoint is live).

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof.

- [ ] `make test-e2e ENV=prod` passes all four ollama cases → CI run `<link>`.
- [ ] `make test-e2e ENV=staging` skips 3 auth cases with documented reason → captured pytest output `<paste>`.
- [ ] Negative-regression demo: remove `api-key-ollama` middleware from prod IngressRoute → `test_ollama_auth_boundary_rejects_anon` fails → restore → passes again → commit log of the temp revert + restore.
- [ ] SOPS rotation demo: rotate `apps.services.ai.ollama.api_key`, run `make apply-middleware-secrets ENV=prod`, re-run E2E → all auth cases still pass → SOPS audit clean.
- [ ] Negative-grep on a fixture run: API key value never appears in pytest output, CI artifacts, assertion messages.

## Test status

- E2E suite: `make test-e2e ENV=prod` → `<x passed, y skipped>`.
- Manual smoke: `<what was exercised, what observed>`.
- No regressions in existing prod E2E suite: `<yes / no>`.

## Decisions made during implementation

- `<list any non-obvious trade-offs>`.

## Promotion candidates

- [ ] Lesson for `kubelab/lessons.md`? Likely "Negative-regression check before merging auth tests prevents the test from passing trivially (asserting the test asserts)".
- [ ] ADR-worthy? No — implementation of ADR-035 testing strategy, not a new architectural decision.
- [ ] New pattern for `00_meta/patterns/`? Possibly — "Auth-boundary E2E test = positive + negative + leak-grep triple" if the pattern repeats for AI-004 / DT-004 / future RAG services.

## Archive checklist

- [ ] `proposal.md` frontmatter → `status: archived`.
- [ ] `mv specs/AI-002-e2e-tests/ → specs/archive/AI-002-e2e-tests/`.
- [ ] Vault `11-tasks.md` AI-002 ticked with PR link.
- [ ] Promotions executed.
