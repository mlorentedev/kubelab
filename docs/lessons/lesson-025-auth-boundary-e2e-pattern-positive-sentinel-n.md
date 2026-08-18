---
id: lesson-025-auth-boundary-e2e-pattern-positive-sentinel-n
type: lesson
status: active
created: "2026-05-23"
owner: manu
tags: [kubelab, lesson]
---

# Auth-boundary E2E pattern: positive + sentinel-negative + leak-grep triple

**Context**: AI-002 introduced 5 E2E cases for the X-API-Key-gated `ollama.kubelab.live` endpoint (Traefik api-key plugin, prod-only). The auth-validation cases resemble a cheap-but-comprehensive proof harness for any plugin-protected service. Same shape applies to AI-004 (Pollex) and DT-004 (widget-proxy) when those land.

**Problem**: Naive auth tests check only `with key → 200`. That proves "plugin happy on correct input" but doesn't prove rejection — a misconfigured plugin that accepts ANY key passes the test. Adding `without key → 403` is the obvious second case but still has a blind spot: a plugin that accepts header *presence* (regardless of value) passes both. And neither catches the rare-but-catastrophic regression where the plugin echoes the candidate key in its error body.

**Solution**: Three orthogonal cases per protected endpoint:

1. **Positive**: `with correct-key → 200` (backend reachable + happy path).
2. **Sentinel-negative**: `with hardcoded-wrong-key → 403`. Sentinel string is HARDCODED in the test (`_WRONG_KEY_SENTINEL = "definitely-not-the-real-key"`), NEVER sourced from SOPS — that decoupling makes the test invariant under key rotation. Proves the middleware validates the *value*, not just header presence.
3. **Leak-grep**: `with hardcoded-wrong-key, assert real-key-from-SOPS not in response body`. Catches the rare echo-the-candidate-key regression.

**Rule**: For every plugin-gated public endpoint, codify the triple. The sentinel-negative is the "test-of-the-test" — its only failure mode is the middleware regressing to accept arbitrary keys, no manual security drill needed. The leak-grep is dirt-cheap (one string comparison) but catches a class of mistake that's invisible to positive+negative testing alone.
