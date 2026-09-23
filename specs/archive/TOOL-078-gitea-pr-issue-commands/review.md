---
spec: "TOOL-078-gitea-pr-issue-commands"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "78e722741e40f02ce0842c6c10f9cb85bb38b5a3"
reviewer: "nan/mimo-v2.5"
date: "2026-09-22"
---

## Adversarial review

**Scope**: TOOL-078-gitea-pr-issue-commands (full diff from `470a9d76...HEAD`, 2 commits)
**Sources**: `specs/TOOL-078-gitea-pr-issue-commands/{proposal,tasks,verification}.md`, `git diff 470a9d76b2a3c399655255b6d2b126e81b68a498...HEAD`, `tests/test_gitea_authoring.py`, `toolkit/features/gitea_authoring.py`, `toolkit/features/gitea_client.py` (lines 766–787), `toolkit/cli/services.py` (lines 1053–1118)

### Spec and task alignment

All six tasks (`T1`–`T6`) are ticked `[x]` and supported by code and tests. The diff adds exactly the files described: `gitea_authoring.py` (feature module with rules), `gitea_client.py` (two new methods), `services.py` (CLI commands), and `test_gitea_authoring.py` (17 tests). No scope creep beyond what the proposal describes.

The proposal's credential rationale ("same identity as `gitea git`", basic-auth, no token) is correctly implemented and asserted in tests. The `gitea_authoring.py` module docstring faithfully explains the "why" from the proposal. The out-of-scope items (reading PR state, merging, editing) are absent.

AC3 (credential absent from argv/output) is verified by `test_the_credential_travels_as_basic_auth_and_nowhere_else` and `test_the_command_prints_the_url_and_never_the_password`. Both assertions are positive (the password IS present in the auth tuple), not vacuous negative checks. AC4 (vault memory update) is verified against the vault — outside this repo's diff but referenced with a commit hash.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|-------------|
| Major | REAL | validation | `pull_payload` does not strip `head`/`base` — whitespace-only strings like `"  "` pass validation (truthy, passes `if not head`) and reach Gitea as-is. The proposal's own module docstring promises "The rules are pure … checked here, before a request exists, so a malformed call is refused with a reason that names the mistake instead of a 422." A whitespace-only branch name is malformed but slips through, contradicting the stated contract. | Reproduced: `pull_payload(head='  ', base='main', title='t', body='')` returns `{'head': '  ', 'base': 'main', 'title': 't', 'body': ''}` instead of raising `AuthoringError`. The title IS stripped via `_title()` but head/base are not — the inconsistency is local and visible. | UNTESTED | code (`gitea_authoring.py:56`) |
| Minor | THEORETICAL | error-handling | `_opened` crashes with raw `KeyError` if the Gitea response lacks `number` or `html_url`. In the CLI this would surface as an unhandled exception rather than a clean `GiteaError` with status code. | Reproduced: `_opened({})` → `KeyError: 'number'`. Real-world risk is low — Gitea's API always includes these fields for 201 responses — but a defensive `try/except KeyError` would match the codebase's "never crash with an internal error" posture. | UNTESTED | code (`gitea_authoring.py:78`) |
| Minor | THEORETICAL | test-coverage | No dedicated CLI test for `issue create` — `pr create` is tested end-to-end but `issue create`'s CLI path (command registration, error handling, output format) is only covered implicitly by `open_issue` unit tests. | `tests/test_gitea_authoring.py` tests `open_issue` and `issue_payload` but not `gitea_issue_create` via `CliRunner().invoke`. | UNTESTED | tests (`test_gitea_authoring.py`) |
| Minor | THEORETICAL | error-handling | Network errors (`requests.ConnectionError`, `requests.Timeout`) propagate as raw exceptions in the CLI, not as `GiteaError`. The `except (AuthoringError, GiteaError)` handler would not catch them, producing a traceback instead of a clean error message. | Code read: `GiteaBasicAuthClient._request` → `session.request()` can raise `requests.ConnectionError`. This is consistent with `gitea_git`'s error handling (same gap exists there), so it is a pre-existing pattern rather than a new defect. | UNTESTED | code (`cli/services.py:1096, 1113`) |

### Evaluator rubric

| Dimension | Grade | Rationale (one line) |
|-----------|-------|----------------------|
| Correctness        | B     | Happy paths fully verified; whitespace-in-head/base validation gap (REAL) contradicts the module's stated contract |
| Verification       | A     | 17 tests passing, positive credential assertions, live verification for AC1/AC2, mutation-verified head==base and title guards |
| Scope              | A     | Diff matches proposal exactly; no creep, no missing pieces |
| Reliability        | B     | Error paths handled (AuthoringError, GiteaError); network errors uncaught but consistent with pre-existing pattern |
| Maintainability    | A     | All functions <40 lines, clear naming, docstrings explain why, frozen dataclass, regex-validated segments |
| Handoff-readiness  | B     | Spec files present with live evidence; `features.json` absent (not part of this repo's spec workflow) |

### Verdict
PASS WITH GAPS

One **REAL** Major finding (whitespace validation gap in `pull_payload`) that contradicts the proposal's own contract ("refused before it leaves the process"). The fix is trivial (strip `head`/`base` or reject whitespace-only) and lives in code, not in the contract set — so it can be applied without invalidating this review. All other findings are THEORETICAL minors.

### Recommended next steps

1. **[code]** In `gitea_authoring.py:pull_payload`, strip `head` and `base` before the validation check, consistent with how `_title` strips `title`. Or reject whitespace-only strings explicitly. This closes the REAL Major finding.
2. **[tests]** Add a CLI test for `gitea_issue_create` mirroring `test_the_command_prints_the_url_and_never_the_password` — same pattern, different command.
3. **[code]** In `gitea_authoring.py:_opened`, catch `KeyError` and raise `AuthoringError` with a message like "unexpected Gitea response: missing number/html_url".
4. **[tests]** Add a test for `pull_payload(head='  ', base='main', ...)` raising `AuthoringError` to prevent regression of the whitespace fix.

None of these are contract-set changes (`proposal.md`, `tasks.md`, `features.json` are untouched). They can all be applied and verified without a re-review cycle.

**Archive advice**: Advisable after fix #1 (the REAL Major). Fixes #2–#4 can follow as a cleanup commit and do not gate archiving.
