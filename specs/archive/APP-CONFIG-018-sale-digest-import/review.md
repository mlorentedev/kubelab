---
spec: "APP-CONFIG-018-sale-digest-import"
verdict: "PASS"
reviewed_sha: "8a9cb9bdc9a1061e7f9a7b48c772424b5c71ee28"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-09"
---

## Adversarial review

**Scope**: APP-CONFIG-018-sale-digest-import
**Sources**: `specs/APP-CONFIG-018-sale-digest-import/{proposal.md,tasks.md,verification.md,features.json}` +
`git diff aaff3dbca49d4ed5f2fddef7663ff6e655106970...HEAD` (declared base; HEAD `8a9cb9bd`).

### Evidence produced in this run

Everything below was executed this session, not read off the spec's claims:

- `git log aaff3dbc..HEAD`: 47 first-parent merges. The spec's own work is 5 of them —
  `e88576dd` (#2090, importer + workflow + tests), `b9bacb80` (#2092, lesson renumber 527→528),
  `500fdd2f` (#2094, owner-set SOPS values), `f7612a00` (#2095, Spanish HTML email),
  `b0c35a17` (#2106, retry-on-200-with-errors). The rest of the declared diff (backup, gitea,
  hermes, open-webui, …) belongs to other PRs merged on the same base and was excluded from this
  spec's scope judgement.
- Contract files touched only by `e88576dd`; working tree clean apart from the launcher's
  `review-request.json`, so no staleness between request and review.
- Spec tests: `pytest tests/test_n8n_shared_credentials.py tests/test_n8n_sale_digest.py
  tests/test_n8n_import.py tests/test_n8n_import_restart.py` → **103 passed**.
- Whole unit suite `-m "not e2e and not infra and not integration"` → **4343 passed, 16 skipped,
  2 xfailed** (verification.md's "3934 passed" was already stale; the suite is green and larger).
- `make lint` → clean (125 files formatted, ruff OK); `mypy toolkit/` → "no issues in 124 source files".
- All seven `features.json` verification commands re-run individually → green, non-vacuous
  (3/14/1/3/5/5/3 tests selected respectively).
- Independent mutation checks (edited, ran, reverted via `git checkout --`, tree verified clean):
  `"secure": True` instead of `port == 465` → 3 failures in `TestSmtpCredentialShape`;
  `problems = []` instead of calling `_unimported_references` → both AC3 refusal tests fail.
  The tests bite.
- AC2 claim reproduced with the test's fake-`kubectl` harness (token removed from the vault):
  `ok=False`, digest workflow absent, but `kubectl` **did** exec `import:credentials` for
  `kubelab-smtp` first (see finding 1).
- AC4 cross-checked against upstream `n8n` `Smtp.credentials.ts` (raw GitHub): field names
  `user`, `password`, `host`, `port`, `secure`, `disableStartTls` (+ optional `hostName`) — the
  rendered payload matches; `port` number, `secure`/`disableStartTls` booleans. (Upstream file
  read at `master`; the `2.12.3` tag name did not resolve — tag-level pin UNVERIFIED.)
- No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags in the spec folder. No secrets in the spec's
  diffs (SOPS ciphertext only; the Cloudflare account id is inline by documented decision —
  README: "an identifier, not a credential").

### Spec and task alignment

- AC1 → `TestProdRun::test_credentials_land_before_the_workflow_that_uses_them`,
  `test_staging_imports_neither_the_digest_nor_smtp`, `test_the_cloudflare_credential_is_a_bearer_header` — ran, pass. Order and "once each" are asserted on the recorded payloads.
- AC2 → `TestFailsClosed` (3× sale value, 4× SMTP value), `test_the_other_workflows_still_import_when_the_digest_cannot`,
  `TestProdRun::test_nothing_secret_reaches_the_output`, `test_the_secrets_travel_on_stdin_never_argv`,
  `tests/test_n8n_import.py::TestPlaceholderResolution::test_every_absent_path_is_named_at_once` — ran, pass.
  Placeholder/secret failure happens before the digest's own credential or workflow exec
  (`_process_spec`: resolve → parse → ids → reference check → secret → kubectl).
- AC3 → `test_a_credential_nothing_imports_is_refused`,
  `test_a_shared_credential_referenced_under_the_wrong_id_is_refused`,
  `test_header_auth_nodes_that_disagree_on_the_id_are_refused` — ran; mutation-killed independently.
- AC4 → `TestSmtpCredentialShape` (5 tests) + upstream field-name check — ran, pass.
- AC5 → `TestSharedLifecycle` (5 tests) — ran, pass.
- AC6 → `TestRegistries` + `test_every_placeholder_it_carries_is_mapped_to_a_path_with_an_owner`
  + `tests/test_secret_expiry.py`/`tests/test_secrets_orphan_audit.py` (34) — ran, pass; a repo-wide
  mapping guard also exists at `tests/test_n8n_issue_creates_task.py:383`.
- AC7 → `TestReadme` (3 tests) — ran, pass; the README's removal steps are consistent with the
  registries (entry + JSON + SOPS block + catalog/PROVIDER_CHECKS/PLACEHOLDER_SSOT lines; `kubelab-smtp` stays).
- Every `[x]` in `tasks.md` has diff evidence; the "14 mutants" claim is plausible and 2 of 14
  were independently re-killed here.
- Test deletions/weakenings: none deleted. One assertion adapted in
  `test_n8n_import_restart.py` (`len(N8N_IMPORT_CATALOG)` → staging-only subset) because the digest
  is prod-only; it still pins the exact publish count and restart-once ordering — justified, not quieter.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Minor | REAL | docs / AC2 wording | README (digest section) and proposal item 5 say an absent sale value fails "before any `kubectl`"; in a real run `kubectl exec import:credentials` for `kubelab-smtp` (plus the other workflows' imports) executes before the digest's placeholder check. AC2 as written ("before any kubectl call **for it**") holds; the absolute phrasing does not. | Reproduced this session: token removed → `ok=False`, digest absent, yet `credential:kubelab-smtp` landed first in the recorded kubectl order | `TestFailsClosed::test_a_missing_sale_value_fails_the_digest_naming_the_path` proves the workflow not landing, not the "no kubectl at all" claim → README claim UNTESTED | docs (`infra/n8n/workflows/README.md`) — outside the contract set; disposition in `verification.md` |
| Minor | THEORETICAL | tests / scheduling | Nothing pins the schedule (`0 8 * * *`) or `settings.timezone: "America/Denver"`. The README instructs "re-export after any UI edit", so a re-export that drops `settings.timezone` moves the digest to the instance default (no TZ/GENERIC_TIMEZONE is set on the n8n Deployment → UTC → 02:00 Denver) with every test green. Correct today and production-observed (lesson-531: the scheduled run arrived 2026-10-07). | `grep -rn 'scheduleTrigger\|cronExpression\|"settings"' tests/` → no hits | UNTESTED (no named test) | tests (pin cron + timezone in `test_n8n_sale_digest.py`) |
| Minor | REAL (measured) | quality | `_process_spec` is 81 lines, `resolve_placeholders` 48 — both over the repo's <40-line rule. Cyclomatic complexity is fine (`ruff --select C901` clean). | ast line count this session; `make lint` + `mypy` clean | n/a (style, not behavior) | code (follow-up refactor) |
| Minor | REAL | spec artifacts (`verification.md`, outside contract set) | Stale evidence: "the `sale_digest` block is not in SOPS yet" (owner set it in #2094, verified encrypted in `prod.enc.yaml`) and "3934 passed" (suite now 4343). | `git show 500fdd2f`; full-suite run this session | n/a | `verification.md` |
| Minor | SPECULATIVE | code | `import_n8n_workflow` returns on an empty `applicable` list *before* `_import_shared_credentials`, so a prod with an empty catalog would stop re-importing `kubelab-smtp`, contradicting the documented invariant "imported for the env whether or not a workflow uses it today". Requires every prod workflow to be removed. | code read, `toolkit/features/n8n_import.py:405-411` | UNTESTED | code (guard) or docs |
| Question | SPECULATIVE | resilience / leak | `_run` logs the pod's stdout on success, so a secret echoed by the n8n CLI itself would reach the terminal; `test_nothing_secret_reaches_the_output` cannot catch it because the fake kubectl returns empty stdout. | code read (`_run`, success path); fake returns `stdout=""` | UNTESTED | tests (feed a sentinel-bearing stdout through the fake) |

No Blocker, no Major. Code-level checklist: injection — the GraphQL query is variable-parameterised
and all data-derived HTML passes `esc()`/`encodeURIComponent()`, pinned by
`test_every_value_that_comes_from_data_is_escaped`; secrets — none committed, SOPS values
ciphertext, payload on stdin only (pinned); auth — credential references fail closed; performance —
no unbounded/blocking paths added; resilience — partial-failure semantics defined and tested
(`test_a_failed_shared_import_holds_back_only_the_workflows_that_need_it`).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All 7 ACs verified by named tests I re-ran, plus a production-observed delivery (lesson-531); held back only by the README "before any kubectl" overstatement and the unpinned schedule promise. |
| Verification       | A | Every `features.json` command re-produced green this session; 4343-test suite, lint, mypy clean; 2/14 mutants independently re-killed; AC4 cross-checked against upstream n8n source. |
| Scope              | B | The 5 spec commits map to the proposal; the declared base also carries ~40 unrelated master merges (excluded), #2094 was the owner's reserved step, #2095/#2106 evolved the artifact with tests + lessons. |
| Reliability        | B | Error paths (missing values, refused refs, failed shared import, partial run) all tested; graceful degradation observed in production; real prod import not re-run here (no cluster). |
| Maintainability    | B | `ruff C901` clean, clear naming and WHY-comments, but `_process_spec` (81) and `resolve_placeholders` (48) breach the <40-line rule. |
| Handoff-readiness  | B | Proposal/tasks/verification/features.json all present, lessons 528 + 531 captured, README operational; `verification.md` carries two stale lines. |

Aggregation: no D, no C → all B or above.

### Verdict
PASS

### Recommended next steps
- Disposition in `verification.md` (outside the contract set — no contract edit requested): the
  README "before any `kubectl`" wording (finding 1), the two stale evidence lines (finding 4),
  and either add the schedule/timezone pin test (finding 2) or ticket it — all three are
  follow-up-sized, none gates archive.
- Findings 3 and 5 are code-side follow-ups (`_process_spec` split; shared-credential import on an
  empty catalog) — ticket or fix, at implementer's discretion.
- Finding 6 (n8n stdout leak path) is a question for the owner: confirm the n8n CLI's
  `import:credentials` output never echoes the payload, or extend the fake to cover it.

**Archive**: `dotf spec archive APP-CONFIG-018-sale-digest-import` is **advisable** in this state —
verdict PASS, frontmatter well-formed, no draft tags, contract files unchanged since the review
request. (Verdict: PASS.)
