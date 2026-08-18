---
id: lesson-263-mutation-drills-require-an-independent-oracle
type: lesson
status: active
created: "2026-05-23"
owner: manu
tags: [kubelab, lesson, testing, security, mutation-testing, ai-001, ai-002]
---

# Mutation drills require an independent oracle

**Context:** AI-002 spec originally proposed a "mutation drill" to test auth: SOPS-tamper the api_key, observe that the previously-working request now fails. Both the test fixture (client) and the middleware (target) read the same SOPS file via the same toolkit codepath.
**Problem:** Codex P1 review on PR #191: this isn't a mutation drill — it's a coordinated rotation. If you tamper SOPS, both actor and target see the new value; the test would PASS even when the middleware was broken (e.g., if it ignored the key entirely). The "test" was tautological — it proved SOPS reads work, not that auth works. False sense of security.
**Solution:** Hardcode a wrong-key sentinel in the test itself, completely independent of SOPS. `test_ollama_rejects_invalid_key` sends `X-API-Key: wrong-sentinel-XYZ` and expects 403. The actor (test) and target (middleware) draw from different sources; a real mutation in the middleware (e.g., accepting all keys) would surface immediately. Pattern: when validating a check, the validator and the checked subject MUST NOT share state. The "wrong-key sentinel" idiom is the cheapest way to break the coupling — zero infra, full coverage. Shipped in PR #192.
**Tags:** `#testing` `#security` `#mutation-testing` `#ai-001` `#ai-002`
