---
id: "AI-002-e2e-tests"
type: spec
status: draft
created: "2026-05-14"
updated: "2026-05-21"
tags: [spec, proposal, ai, e2e, tests, ollama]
template_version: "1.0"
---

# AI-002: E2E coverage for AI services (Ollama health + auth boundary)

## Why

The current E2E suite (`tests/e2e/`) covers user-facing app endpoints (web, api, blog, grafana, gitea, …) but has zero coverage for the AI surface. As AI-001 introduces a public `ollama.kubelab.live` endpoint gated by an X-API-Key middleware (per ADR-035), there is no automated proof that:

1. The Ollama backend is reachable and serving (`/api/tags` returns a non-empty model list).
2. The auth middleware actually rejects unauthenticated requests (a regression that opens `/api/*` to the world would otherwise go undetected until billing pain or abuse).
3. The Bearer-header forward-compat path works (so Stage 2 OIDC/JWT migration per ADR-035 lands cleanly).

Without this coverage, a Traefik plugin update, a Middleware misconfig, a SOPS key drift, or an Ollama upgrade can silently break either liveness or the security boundary.

Vault refs: `kubelab/11-tasks.md` AI-002 entry, ADR-035, sister spec AI-001.

## What

Add E2E test cases under `tests/e2e/` that, when run against `ENV=staging` or `ENV=prod`, exercise:

1. **Health**: `GET https://ollama.<env-domain>/api/tags` returns 200 with at least one model in the JSON response.
2. **Auth boundary (prod only)**: `GET https://ollama.kubelab.live/api/tags` WITHOUT any auth header returns 403. Body contains no Ollama-internal data. Plugin `dtomlinson91/traefik-api-key-middleware` emits `403` (not `401`) for all unauthenticated cases per its README — assert on `403` exactly.
3. **Auth happy path (prod only)**: same request WITH `X-API-Key: <key from SOPS>` returns 200 + model list.
4. **Bearer forward-compat (prod only)**: same request WITH `Authorization: Bearer <key from SOPS>` returns 200 (proves the plugin's Bearer mode is enabled — guards against future Middleware drift breaking Stage 2 migration).
5. **No leakage**: response body of the 403 contains no Beelink/ace2 hostname, no model list, no internal error stack.

Tests read the API key from SOPS via the existing fixture pattern (no key in repo, no key in test code). Tests skip with a clear reason when `ENV=staging` (staging is VPN-only, no auth needed there) for cases #2/#3/#4.

## Out of scope

- Inference correctness (response from `/api/generate` is non-deterministic; only liveness probe via `/api/tags` here).
- Rate-limit / throttling tests (AI-003 territory).
- Per-tenant API key management (single shared key in v1, per ADR-035).
- Load / concurrency testing (AI-006 if it ever happens).
- Pollex / Jetson AI tests (AI-004 spec).

## Risks / open questions

1. **Test pollution of Ollama logs.** Repeated E2E hits inflate Ollama access logs and Beelink/ace2 disk usage marginally. Mitigation: tests gated to one run per CI job (cron + manual `make test-e2e`), not per-PR. Acceptable.
2. **Auth-boundary test could be flaky if SOPS key rotation is mid-flight.** If a key is rotated but `make apply-middleware-secrets` hasn't propagated yet, the happy-path test fails spuriously. Mitigation: rotation runbook (PR-C closing) must include "redeploy then re-run E2E" as the canonical order.
3. **Bearer header test depends on plugin configuration.** If the Middleware later disables Bearer mode (`bearerHeader: false`) to enforce X-API-Key-only, this test breaks intentionally — that IS the desired guard (forces the deciding human to update both Middleware and ADR-035 anchored decisions in lockstep).

No remaining open questions.

## Acceptance criteria

- [ ] `make test-e2e ENV=prod` runs and passes all four ollama cases (health + 3 auth variants).
- [ ] `make test-e2e ENV=staging` runs and skips the 3 auth cases with a clear "staging is VPN-only" reason; health case still runs and passes.
- [ ] **Mutation drill (test-of-the-test) via SOPS tampering, NOT IngressRoute removal**: temporarily rotate `apps.services.ai.ollama.api_key` in SOPS to a known-wrong value, run `make apply-middleware-secrets ENV=prod`, then re-run `make test-e2e ENV=prod` — `test_ollama_health_authenticated` MUST fail with 403 (proves the happy-path test actually exercises the middleware and would catch a real auth break). Restore the real key + re-apply + re-run → passes again. This replaces the original "remove middleware from IngressRoute" drill because that approach exposes `ollama.kubelab.live` to anonymous traffic during validation (security/cost risk on a public endpoint).
- [ ] Rotating the SOPS `apps.services.ai.ollama.api_key` and re-applying produces a passing test on the new value (proves SOPS fixture pickup works end-to-end).
- [ ] No API key value ever appears in test output, CI logs, or assertion messages (negative-grep on a fixture run).

## References

- Vault: `10_projects/kubelab/11-tasks.md` AI-002 entry
- ADR: `30-architecture/adrs/adr-035-api-auth-strategy.md`
- Sister spec: `specs/AI-001-ollama-public/`
- Existing E2E pattern: `tests/e2e/conftest.py`, `tests/e2e/expectations.py`
- Component: `apps/services/ai/ollama` (SSOT entry in `infra/config/values/common.yaml`)
