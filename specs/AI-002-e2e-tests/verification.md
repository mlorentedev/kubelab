---
tags: [spec, verification]
created: "2026-05-13"
updated: "2026-05-23"
---

# Verification - AI-002-e2e-tests

> Filled at implementation close (PR `feat/ai-002-ollama-e2e`, 2026-05-23). AI-001 PR-C merged 2026-05-22 (#195); prod endpoint live since.

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof.

- [x] `make test-e2e ENV=prod` passes all five ollama cases → run on `feat/ai-002-ollama-e2e` HEAD, 2026-05-23: `5 passed in 1.96s` against `ollama.kubelab.live`. CI link to be appended once PR opens.
- [x] `make test-e2e ENV=staging` skips 4 auth cases with documented reason → `1 passed, 4 skipped in 0.81s`. Skip reasons: `"staging is VPN-only — no middleware gates the endpoint"` / `"staging is VPN-only — no middleware to reject"` / `"staging is VPN-only — no middleware to honor Bearer"` / `"staging is VPN-only — no middleware emits 403 bodies"`.
- [x] `test_ollama_rejects_invalid_key` passes as part of the standard `make test-e2e ENV=prod` run → this IS the test-of-the-test. The wrong-key sentinel `"definitely-not-the-real-key"` is hardcoded in `test_ollama_public.py` (module-level constant `_WRONG_KEY_SENTINEL`), so the assertion is independent of any SOPS state. If the middleware ever stops rejecting arbitrary keys, this test fails automatically on the next CI run.
- [x] Negative-grep on a fixture run: `test_ollama_no_key_leak_in_403_body` asserts the SOPS-resolved key value never appears in the 403 body. Passes against live `ollama.kubelab.live`. Pytest output is grep-clean (the key is read from a session-scoped fixture, never logged, never templated into assertion messages).
- [ ] SOPS rotation demo (positive path): rotate `apps.services.ai.ollama.api_key`, run `make apply-middleware-secrets ENV=prod`, re-run E2E → expected: all five still pass (sentinel test invariant under rotation by design). Not exercised in this PR; deferred to next scheduled rotation per runbook `40-runbooks/ollama-api-key-rotation.md`.

## Test status

- E2E suite: `make test-e2e ENV=prod` → 5 passed, 0 skipped (ollama subset). Full suite: 64 passed, 19 skipped, 3 preexisting failures unrelated to AI-002 (`test_security_headers_present[api|web]`, `test_hsts_header[web]`) — root-caused to prod `infra/k8s/overlays/prod/generated/ingress.yaml` missing `secure-headers` middleware on api/web routes; tracked as SEC-K8S-001 in `kubelab/11-tasks.md`.
- Manual smoke (2026-05-22 prod cutover, AI-001 closure): X-API-Key 200, no-header 403, wrong-key 403, Bearer 200 — all verified by hand. Now codified.
- No regressions in existing prod E2E suite: the 3 failures predate this branch (verified by running the same 4 cases on master: same 3 fail).

## Decisions made during implementation

- **New file `test_ollama_public.py` rather than extending `test_health.py`**: ollama in `EXPECTATIONS` has `skip_in_envs=("dev", "prod")` (was staging-only before AI-001). Refactoring `expectations.py` to express "auth-gated in prod" would have rippled into `test_security_headers.py` and `test_tls_routing.py`; out of scope. A dedicated file keeps auth-boundary semantics local.
- **Hardcoded sentinel as module constant, not fixture**: `_WRONG_KEY_SENTINEL = "definitely-not-the-real-key"` is intentionally a literal string in the test module. Reading it from a fixture would tempt a future refactor to source it from SOPS, breaking the test-of-the-test invariant.
- **Health test sends `X-API-Key` only in prod**: staging Ollama IngressRoute has no plugin Middleware, so the header is ignored. Sending it anyway would conflate two code paths; conditional header set on `env == "prod"` keeps the staging case a clean liveness probe.
- **Bearer test asserts 200 (not just "not 403")**: tighter than strict-necessary, but catches plugin misconfiguration that might silently degrade Bearer to 401/403 while X-API-Key still works.

## Promotion candidates

- [x] Lesson for `kubelab/lessons.md`: "Auth-boundary E2E = positive + sentinel-negative + leak-grep triple. Hardcoded sentinel decouples client from SOPS, making the test invariant under rotation." → To capture when this pattern repeats for AI-004 / DT-004.
- [ ] ADR-worthy? No — implementation of ADR-035 testing strategy, not a new architectural decision.
- [ ] New pattern for `00_meta/patterns/`? Defer — promote only after the pattern repeats in AI-004 (Pollex) or DT-004 (widget-proxy).

## Archive checklist

- [ ] `proposal.md` frontmatter → `status: archived`.
- [ ] `mv specs/AI-002-e2e-tests/ → specs/archive/AI-002-e2e-tests/`.
- [ ] Vault `kubelab/11-tasks.md` AI-002 ticked with PR link.
- [ ] Promotions executed.
- [ ] SEC-K8S-001 ticket opened in `kubelab/11-tasks.md` (prod `secure-headers` middleware drift for api/web — surfaced during AI-002 verification).
