---
id: lesson-023-fail-closed-fixtures-in-security-e2e-suites
type: lesson
status: active
created: "2026-05-23"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# Fail-closed fixtures in security E2E suites

**Context**: AI-002 PR #201 added `ollama_api_key` fixture in `tests/e2e/conftest.py` that returned `None` when SOPS decryption failed or `apps.services.ai.ollama.api_key` drifted. Three prod auth-path tests (`health_authenticated`, `bearer_forward_compat`, `no_key_leak_in_403_body`) handled the None with `if not ollama_api_key: pytest.skip(...)`.

**Problem**: Codex flagged P1. The skip semantics ("this condition doesn't apply") is wrong for a missing-input scenario that should ALWAYS be present in prod. A broken SOPS pipeline = silent green CI run, exactly the regression the suite was supposed to catch. `pytest.skip` ≠ fail-closed; in security suites, skipping = false reassurance.

**Solution**: Moved the policy into the fixture itself (PR #202): `pytest.fail(...)` when `env == "prod"` and key is missing/unresolved. Staging/dev keep returning None — auth-gated tests already gate themselves out via the `env != "prod"` check. Tests dropped the duplicate skip guards and `assert key is not None` instead.

**Rule**: For security E2E fixtures with env-dependent invariants, the FIXTURE owns the invariant — never the test body. "If condition X must hold in env Y, the fixture must `pytest.fail` (not `pytest.skip`) in env Y when X fails." Skips are reserved for "this test doesn't apply here", never "this input is missing but I don't want to fail". Centralizing the invariant in one place prevents future contributors from re-introducing fail-open behavior via duplicated checks.
