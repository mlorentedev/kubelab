---
tags: [spec, tasks]
created: "2026-05-13"
updated: "2026-05-21"
---

# Tasks - AI-002-e2e-tests

> TDD order. One task = one focused commit. This spec depends on AI-001 PR-C being merged (Ollama public endpoint live).

## Setup

- [ ] Branch from main: `feat/AI-002-ollama-e2e-tests` (after AI-001 PR-C lands).
- [x] `proposal.md` complete; acceptance criteria testable; no open questions.

## Implementation

- [ ] Add fixture: `ollama_api_key` in `tests/e2e/conftest.py` — resolves `apps.services.ai.ollama.api_key` from SOPS via existing SOPS-loader fixture pattern. Skip with reason if missing in env.
- [ ] Write failing test `test_ollama_health_authenticated` — `GET /api/tags` with `X-API-Key` returns 200 + JSON `models` array non-empty. Run on `staging` (no auth used, header ignored) AND `prod` (auth required).
- [ ] Write failing test `test_ollama_auth_boundary_rejects_anon` — `GET /api/tags` with NO auth headers returns 403. Skip in staging (VPN-only, no auth required). Negative-assert body does not contain "ollama", "models", or any host name.
- [ ] Write failing test `test_ollama_bearer_forward_compat` — `GET /api/tags` with `Authorization: Bearer <key>` returns 200. Skip in staging. Proves plugin Bearer mode is enabled (Stage 2 OIDC migration prerequisite).
- [ ] Write failing test `test_ollama_no_key_leak_in_403_body` — full text of the 403 response is grep-clean for the actual API key value (extra paranoia — plugin shouldn't echo, but verify).
- [ ] Implement: tests are mostly httpx/requests calls against the fixture URL + auth header — minimal logic. Move shared assertions to a helper if duplication grows.
- [ ] Refactor: if more than 3 AI services adopt the X-API-Key pattern (DT-004 widget-proxy, AI-004 Pollex), extract a parameterized fixture `auth_protected_service(name)` instead of one-off tests per service.

## Closing

- [ ] All four E2E tests pass on `make test-e2e ENV=prod`.
- [ ] `make test-e2e ENV=staging` passes the health case; 3 auth cases skipped with documented reason ("staging is VPN-only").
- [ ] Negative-regression check executed manually once: remove `api-key-ollama` middleware from prod IngressRoute, re-run tests → 403/Bearer/no-leak cases fail as expected → restore middleware.
- [ ] No API key value in any test output / pytest captured stdout / CI artifact.
- [ ] `verification.md` filled with concrete CI run links.
- [ ] PR opened referencing `specs/AI-002-e2e-tests/`.
- [ ] AI-002 ticked in `kubelab/11-tasks.md` with PR link.
