---
spec: "TOOL-062-gitea-actions-secrets"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "a616feb58f2ed0d139d8482f6b0140fb1933a7c7"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-10"
---

## Adversarial review

**Scope**: TOOL-062-gitea-actions-secrets (round 2; whole change vs base `d99581349a251d3d9a05071d899240252642bee3`)
**Sources**: `specs/TOOL-062-gitea-actions-secrets/{proposal.md,tasks.md,verification.md,features.json,review-round1.md}`; `git diff d99581349a251d3d9a05071d899240252642bee3...HEAD`; implementation in `toolkit/features/gitea_actions_secrets.py`, `toolkit/features/gitea_client.py` (`list_actions_secret_names`, `put_actions_secret`), `toolkit/cli/services.py` (`gitea actions-secrets`), catalog entries in `toolkit/features/secrets_manager.py`, tests in `tests/test_gitea_actions_secrets.py`.

### Spec and task alignment

- All 7 acceptance criteria are mapped to named tests / `features.json` entries (AC7 by design is the by-effect check). Every `[x]` in `tasks.md` I could check has diff evidence; no `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain in the spec files.
- **Round-1 Blocker (escaped secret in an error echo) is genuinely fixed.** `_redact` now replaces five encodings (verbatim, JSON-ascii, JSON-utf8, Go-JSON `\u0026`-form, Python-repr). I red-green verified it: mutating `_redact` back to verbatim-only makes 4 of the 5 `test_a_forge_error_that_echoes_an_escaped_value_is_redacted[…]` params FAIL; with the fix restored all 40 tests in the file pass. Round-1's Minor (asserting against `repr(report)`) is also fixed — the test now reads the recorded message itself.
- **Round-1 Major (undeclared secrets on repositories the catalog never names) — I accept the disposition, with the reading recorded here.** The proposal scopes the plan to "For each repository … the declared names, the live names …", and the live-name GET requires a repository argument the spec never enumerates; a forge-wide sweep would be machinery the proposal does not declare. Under that reading AC5 ("a live secret the catalog does not declare is reported and left in place") is satisfied for every repository in scope, and `TestThePlan::test_an_undeclared_live_secret_is_reported_and_never_removed` pins it. The residual scope ambiguity is tracked in #2165 (TOOL-105), confirmed OPEN via `gh issue view 2165`. **If the owner reads AC5 forge-wide instead, that is a contract-wording change and this verdict does not cover it — re-review would be required.**
- Acceptance commands reproduce fresh: `pytest tests/test_gitea_actions_secrets.py -q --no-cov` → **40 passed**; each `features.json` verification `-k` command reproduces its stated count (f1=1, f2=1, f3=2, f4=7, f5=1, f6=3). Full suite `pytest -q --no-cov` → **4424 passed, 16 skipped, 2 xfailed, 0 failed** (7m01s; verification.md's 2587-count predates later specs landing — stale but not false for its date). `ruff check` + `ruff format --check` on the changed modules → clean; `mypy toolkit` (the repo gate) → "Success: no issues found in 125 source files".
- AC7 (resume publish-drive uploads to Drive) is external and **UNVERIFIED by me**; it rests on the recorded run-96 evidence in verification.md / #1936.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Minor    | REAL    | verification | `verification.md` claims "mypy … and the test file: clean", but `mypy tests/test_gitea_actions_secrets.py` reports 6 `arg-type` errors: `_FakeForge.put_actions_secret(owner, repo, name, value)` does not match the `SecretWriter` protocol's `(owner, name, secret_name, value)`. The repo's actual gate (`mypy toolkit`) is clean — the claim as written does not reproduce. | my run of mypy on the test file (errors at lines 245, 258, 268, 449, 500, …); `mypy toolkit` → success | n/a (type-check claim) | tests (rename fake params) or `verification.md` wording |
| Minor    | REAL    | tests | The formatted undeclared row — `? {repo} {name} not declared in the catalog -- reported, never deleted` — is asserted by no test; `grep "not declared in the catalog" tests/` returns nothing. AC5's terminal output, and the CLI path that prints it, are only pinned at the planner tuple level (with `targets=()`, a state the CLI cannot itself produce). | grep over `tests/`; `_CliForge` fixtures always list exactly the declared names | `TestThePlan::test_an_undeclared_live_secret_is_reported_and_never_removed` covers the planner only → format/CLI row **UNTESTED** | tests |
| Minor    | REAL    | quality | The new CLI command `gitea_actions_secrets` (`toolkit/cli/services.py` 1240–1316) is ~77 lines (~62 excluding blanks/comments/docstring), over the repo Law's <40-line function limit. | `awk` line count over the function | UNTESTED (no function-length gate) | code |
| Question / assumption | REAL (behavior) / ambiguity (violation) | spec | AC5's wording is readable forge-wide; the implementation reports undeclared secrets only on repositories the catalog names. Dispositioned in round 2 as in-spec (proposal "For each repository" scoping) + ticket #2165 (open). Owner should confirm the reading. | proposal What §3 vs `toolkit/cli/services.py` loop over `{t.repo for t in targets}`; `gh issue view 2165` → OPEN, "TOOL-105: the Actions secrets report never sees a repository the catalog does not name" | `TestThePlan::test_an_undeclared_live_secret_is_reported_and_never_removed` (planner scope) | spec — **only** if the forge-wide reading is confirmed, which would require a contract edit and re-review |
| Minor    | SPECULATIVE | security | `_redact` is a floor, not a guarantee (its own docstring): an error body carrying the value in an encoding outside the five forms (base64, URL-encoding, split across a line wrap) would still leak. No such encoding observed in Gitea responses. | code read of `_redact` in `gitea_actions_secrets.py` | `test_a_forge_error_that_echoes_an_escaped_value_is_redacted` covers the five listed forms | code — surface only; do not gate |

Round-1's Blocker (escaped echo) and its Minor (repr-assertion) are recorded as **fixed and red-green verified above** — not open findings.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | AC1–AC6 verified by named, freshly passing tests; AC5's scope reading is an accepted, ticketed ambiguity; AC7 external. |
| Verification       | B | Every features command and the full suite reproduce, but one stated claim (mypy on the test file) is false and AC7 is attested, not reproducible here. |
| Scope              | A | Diff matches the proposal; the later fae-brain entry (#2137) is the proposal's own declared follow-through with its test literal updated; no creep found in the spec's files. |
| Reliability        | B | Per-repo unreachable isolation, per-secret failure recording, empty-at-write refusal all handled and tested; no crash path found. |
| Maintainability    | B | Pure planner, clear naming, small functions — except the 77-line CLI command over the <40-line law. |
| Handoff-readiness  | A | Dispositions recorded in verification.md, lesson-545 captured, follow-up ticket #2165 open, spec files complete. |

### Verdict
PASS WITH GAPS

No blockers; no open Major after the round-1 dispositions were re-checked against the code; rubric all B or above. The gaps are the four tracked items above (three Minors, one Question).

### Recommended next steps

- **tests**: add one CLI-level test where `_CliForge` lists an extra undeclared name and assert the `? … reported, never deleted` row appears in the output (closes the UNTESTED format row). Disposition in `verification.md` or a follow-up ticket.
- **tests or verification.md**: rename `_FakeForge.put_actions_secret`'s parameters to the protocol's `(owner, name, secret_name, value)` (or correct the mypy claim in `verification.md`) — `verification.md` is outside the contract set, so this cannot stale the review.
- **spec (conditional, owner's call)**: confirm the "per declared repository" reading of AC5. If the owner wants the forge-wide reading, that edits `proposal.md` (contract set) → fix then re-review; otherwise leave AC5 as-is and let #2165 carry the enumeration work.
- **code (optional)**: split `gitea_actions_secrets` to comply with the <40-line function rule.
- No contract-set edits are required for this verdict; do not head any follow-up with "before archive".
