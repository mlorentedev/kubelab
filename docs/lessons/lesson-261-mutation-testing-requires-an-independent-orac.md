---
id: lesson-261-mutation-testing-requires-an-independent-orac
type: lesson
status: active
created: "2026-05-22"
owner: manu
tags: [kubelab, lesson, testing, security, mutation-testing, ai-001, adr-035]
---

# Mutation testing requires an independent oracle

**Context:** Designing a "test-of-the-test" for the AI-001 X-API-Key middleware (Traefik plugin dtomlinson91/traefik-api-key-middleware). The first version of the acceptance criterion (PR #191) said: "temporarily rotate `apps.services.ai.ollama.api_key` in SOPS to a known-wrong value, re-apply, observe `test_ollama_health_authenticated` MUST fail with 403". The intent was to prove the test actually exercises the middleware (would catch a real auth break). Codex P1 review caught a logic flaw: the test fixture (`ollama_api_key` per `proposal.md:35`) ALSO reads from SOPS. Rotating SOPS rotates BOTH sides — the client sends the rotated value, the middleware expects the rotated value, the test still passes with 200. The "MUST fail" assertion cannot be satisfied under normal conditions. The drill is an unreliable regression detector.
**Problem:** If the actor (client) and the target (server under test) consult the same source of truth, a coordinated change is NOT a mutation — it's a consistent update. Most "mutation testing" patterns that rotate a shared secret silently devolve into rotation tests. The "test of the test" requires that the actor remain in a known *previous* or *adversarial* state while the target moves. Without that disjunction, you cannot prove the test catches a regression.
**Solution:** Use a hardcoded sentinel in the test that is *deliberately* not read from the shared source of truth. For AI-001: `test_ollama_rejects_invalid_key` sends `X-API-Key: definitely-not-the-real-key` (string literal in the test file, NOT a SOPS lookup). The client and the middleware no longer share a moving source of truth — the assertion (status_code == 403) holds independently of any SOPS rotation, and the test fails iff the middleware ever accepts arbitrary keys. Zero operational cost (runs on every CI pass), no manual drill, no IngressRoute touched, no SOPS tampering. Pattern is reusable: any auth-protected endpoint can ship a `test_<service>_rejects_invalid_key` companion to `test_<service>_health_authenticated` as a permanent test-of-the-test. Codified in `specs/AI-002-e2e-tests/proposal.md` acceptance criterion #3. Candidate for promotion to `00_meta/patterns/pattern-mutation-oracle.md` when the pattern recurs in AI-004 / DT-004 / RAG.
**Tags:** `#testing` `#security` `#mutation-testing` `#ai-001` `#adr-035`
