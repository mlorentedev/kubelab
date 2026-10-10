---
spec: "NOTIFY-001"
verdict: "PASS WITH GAPS"
reviewed_sha: "fcd259ef2b176bc0f16288960a0624837003cfc1"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-10-10"
---
## Adversarial review

**Scope**: NOTIFY-001
**Sources**: `specs/NOTIFY-001/{proposal,tasks,verification}.md`, `git diff 6cc27e0bbb198df40915085778b1c3c5a7db3fb5...HEAD`

### Spec and task alignment
- **Apprise Routing**: Apprise is configured with `page` and `log` tiers in `apprise-secrets` and n8n natively routes requests by mapping input parameters to these tags.
- **Webhook Auth**: The workflow restricts calls utilizing n8n's Header Auth natively, avoiding the need for `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` to read environmental variables in the JS node.
- **hermes-nan migration**: `tasks.md` documents `hermes-nan` as retired and handled via other mechanisms.
- All Acceptance Criteria evaluated.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | routing | The JavaScript routing logic inside `notify-router.json` that routes by domain (e.g., `vault`, `deploy`, `agent`) is not covered by any automated test. The smoke test probes only the `page` and `log` paths, leaving the rest of the JS logic untested in CI. | `test_notify_smoke.py` only defines probes for page and log. | UNTESTED | tests |
| Minor | THEORETICAL | auth | While the smoke test asserts a missing header and a wrong secret are rejected, it does not probe a malformed authorization header (e.g. `Basic <token>` or `Bearer` without token) to ensure n8n doesn't crash or fail open. | `tests/test_notify_smoke.py` auth probes | `tests/test_notify_smoke.py` | tests |
| Minor | SPECULATIVE | tests | The `toolkit infra n8n smoke` CLI command defaults `verify_tls` to False for all environments, which could silently accept a broken TLS cert if run manually against prod. | `toolkit/cli/infra.py` defaults | UNTESTED | code |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Criteria met on happy path; minor gaps in testing malformed payloads. |
| Verification       | C | Evidence covers stated criteria, but Apprise routing JS logic for specific domains (vault/deploy/agent) is untested. |
| Scope              | A | Diff matches proposal exactly; no scope creep observed. |
| Reliability        | B | Most error paths handled; webhook gracefully handles undefined fields by defaulting to log/info. |
| Maintainability    | B | n8n workflow JS is well structured; Cyclomatic Complexity is low. |
| Handoff-readiness  | A | Spec updates included and verification documented. |

### Verdict
PASS WITH GAPS

### Recommended next steps
- Add a named automated test for the `vault`, `deploy`, and `agent` JS routing logic in `notify-router.json`, as required by the UNTESTED Major finding.
- Expand `tests/test_notify_smoke.py` to assert correct behavior when a malformed auth header is provided.
- Change the `verify_tls` default in `toolkit infra n8n smoke` CLI to `env == "prod"` to prevent silently ignoring TLS errors in production.
