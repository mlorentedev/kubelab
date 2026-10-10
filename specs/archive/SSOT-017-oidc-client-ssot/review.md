---
spec: "SSOT-017-oidc-client-ssot"
verdict: "PASS WITH GAPS"
reviewed_sha: "74fe86cb0d319a4a704527d2bf1d98e4919e5b6e"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-10-10"
---
## Adversarial review

**Scope**: SSOT-017-oidc-client-ssot
**Sources**: `specs/SSOT-017-oidc-client-ssot/{proposal,tasks,verification}.md`, PR #1780 (`c4976141`), diff base `2a4b13489f6d9b6caa78db12b0d99d02cce3a13d`

### Spec and task alignment
- All acceptance criteria are met, with the exception of the prod logins for `argocd` and `vikunja-oidc` (AC5), which were deferred to #2154.
- `configuration.yml` has been successfully stripped of the `clients:` block, and the new generated `oidc-clients.yml` acts as the single source of truth for Authelia OIDC configurations.
- `sync_oidc_hashes.py` has been completely retired.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | validation | Missing `token_endpoint_auth_method` values validation. The generator verifies the field's presence but not its value. A typo (e.g., `basic` instead of `client_secret_basic`) will pass generation but break SSO for that client at runtime. | Code inspection of `_validate` in `toolkit/features/oidc_clients.py` | UNTESTED | code + tests |
| Major | THEORETICAL | validation | Duplicate `client_id` in `common.yaml` results in duplicate entries in `oidc-clients.yml`. The list appending logic in `resolve_clients` doesn't enforce uniqueness, which could cause Authelia to reject the configuration on startup. | Manual test of `build_clients_file` with duplicate client ids | UNTESTED | code + tests |
| Minor | THEORETICAL | reliability | Missing `path` or `domain` inside the `redirect` object throws an unhandled `KeyError` in `_redirect_uri` instead of raising an `OidcClientError` with the client name. | Manual test throwing `KeyError('domain')` | UNTESTED | code + tests |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Acceptance criteria mostly met; partial gaps in AC5 (prod logins) deferred to #2154. |
| Verification       | A | Excellent reproducible tests (`tests/test_oidc_clients.py`) and manual verification steps included. |
| Scope              | A | Diff aligns precisely with the proposal; no scope creep. |
| Reliability        | B | Most error paths are handled nicely; missed edge cases around missing redirect keys (`KeyError`) and unvalidated auth methods. |
| Maintainability    | A | Code is clean, well-documented, and cyclomatic complexity is well within limits (max CC is 8 for `_validate`). |
| Handoff-readiness  | A | Clear next steps, lessons captured, and ADR-040 updated. |

### Verdict
PASS WITH GAPS

### Recommended next steps
- Validate `token_endpoint_auth_method` against a list of known supported values (`client_secret_basic`, `client_secret_post`, etc.).
- Ensure `client_id` uniqueness during validation in `resolve_clients`.
- Handle missing `domain` and `path` keys inside `redirect` gracefully by raising `OidcClientError`.
- Ensure prod logins for `argocd` and `vikunja-oidc` are fully completed in #2154 before archiving.
