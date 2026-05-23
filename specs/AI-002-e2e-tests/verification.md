---
tags: [spec, verification]
created: "2026-05-13"
updated: "2026-05-21"
---

# Verification - AI-002-e2e-tests

> Skeleton — fill at implementation time (AI-002 cannot start until AI-001 PR-C merges and the prod Ollama endpoint is live).

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof.

- [ ] `make test-e2e ENV=prod` passes all five ollama cases → CI run `<link>`.
- [ ] `make test-e2e ENV=staging` skips 4 auth cases with documented reason → captured pytest output `<paste>`.
- [ ] `test_ollama_rejects_invalid_key` passes as part of the standard `make test-e2e ENV=prod` run → this IS the test-of-the-test (no manual drill, no IngressRoute touched, no SOPS rotated). The wrong-key sentinel is hardcoded in the test, so the assertion is independent of any SOPS state — if the middleware ever stops rejecting arbitrary keys, this test fails automatically on the next CI run.
- [ ] SOPS rotation demo (positive path): rotate `apps.services.ai.ollama.api_key` to a new valid value, run `make apply-middleware-secrets ENV=prod`, re-run E2E → all five cases still pass (including the wrong-key one, since the sentinel does not change) → SOPS audit clean.
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
