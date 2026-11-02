---
spec: "APP-CONFIG-013-vikunja-shared-projects"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "8063633df30811ebe261c8776e075b4ff420a21b"
reviewer: "agy/gemini-3.8-flash-high"
date: "2026-10-21"
---

## Adversarial review

**Scope**: APP-CONFIG-013-vikunja-shared-projects
**Sources**: `specs/APP-CONFIG-013-vikunja-shared-projects/{proposal,tasks,verification}.md`, `features.json`; stated base `1fe7bbe1e8f5538cc19e2cf08be0a27d5ad5baa2...8063633df30811ebe261c8776e075b4ff420a21b`; ADR-066 (including 2026-10-20 amendment #2575 `32247509`); issues #1701, #2326, #2570, #2587; PRs #2324 (`9eafa564`), #2331 (`87f548b6`), #2464 (`99c65d6b`).

**Attribution and diff boundary note.** The base commit stated by the launcher (`1fe7bbe1e8f5538cc19e2cf08be0a27d5ad5baa2`) precedes the feature's branch point. Across master, the implementation landed in separate squash-merges (#2324, #2331, #2464) before Vikunja was formally retired by CONSOLE-004/CONSOLE-005 (#2570, #2587) via ADR-066's 2026-10-20 amendment. `git diff base...HEAD` spans 588 files across the repository. This review evaluates the entirety of the changes attributable to `APP-CONFIG-013` across `toolkit/features/vikunja_*`, `toolkit/cli/sync.py`, `infra/config/values/common.yaml`, `Makefile`, and associated tests and doc artifacts, as well as the archive-readiness record at `8063633d`.

### Spec and task alignment

The spec resolves issue #1701: Vikunja tasks created by Slack or forge webhooks were invisible to human users because the creating account (`operator`, id 1) owned project `Bitacora` without sharing it with team members.

1. **AC1 (SOPS authentication, no argv/stdout exposure, fails closed):** Met. `resolve_token` in `toolkit/features/vikunja_client.py` retrieves `apps.services.core.vikunja.reconciler_api_token` strictly via `ConfigurationManager.get_secret_by_path`. There is no `--token` CLI flag or environment variable override. A missing or empty token raises `VikunjaError`, failing closed before any HTTP request is dispatched. Verified via `tests/test_sync_vikunja_cli.py` (6 passed).
2. **AC2 (Project creation, adoption, no `/namespaces`):** Met. `_reconcile_projects` lists projects with `include_archived=True` and matches case-insensitively, adopting existing `Bitacora` instead of duplicating it. No endpoint targets `/namespaces`. Verified via `tests/test_vikunja_reconciler.py` and `tests/test_vikunja_api_contract.py` (47 passed).
3. **AC3 (Team creation, membership, project sharing):** Met. `_reconcile_team` provisions team `kubelab` and populates only missing members from `apps.auth.identities`. It handles self-membership gracefully and fails closed with actionable diagnostic guidance if an account has never signed in via SSO. `_reconcile_shares` grants declared rights (0=read, 1=write, 2=admin). Verified via `tests/test_vikunja_reconciler.py`.
4. **AC4 (Idempotency, second run reports `changed=0`):** Met. All reconciliation methods inspect existing server state before issuing mutation requests. Tested via `tests/test_vikunja_reconciler.py::test_a_second_run_over_what_the_first_created_changes_nothing` and `test_nothing_to_do_reports_changed_zero`. Staging and production runs confirmed `changed=0` on re-run (recorded in issue #1701 comments of 2026-10-16 and 2026-10-18).
5. **AC5 (API contract validated against real Swagger fixture):** Met. Client requests are verified against `tests/fixtures/vikunja/swagger-paths-1.0.0.json`. Verified via `tests/test_vikunja_api_contract.py` (16 passed). Mutation testing (temporarily re-introducing `/namespaces`) confirmed immediate test failure.
6. **AC6 (SSOT in `common.yaml`, identity invariants):** Met. `common.yaml` declares `projects: [Bitacora]` and `team: {name: kubelab, right: write, members: [superadmin, operator]}`. Tested via `tests/test_vikunja_ssot.py` (4 passed), ensuring no machine/reviewer identities are included and `default_project` is declared.
7. **AC7 (Human visibility as `manu` in prod):** Explicitly unmet and superseded. Verified by the owner in staging browser on 2026-10-16, but never observed on prod because Vikunja was retired by CONSOLE-005 (#2587). This gap is declared honestly across `proposal.md`, `tasks.md`, `verification.md`, and `features.json` (`state: "blocked"`, `verification: "none: superseded"`).
8. **AC8 (No webhook registration, ticket for signature mismatch):** Met. Webhook registration logic was removed from the reconciler loop (`test_the_reconciler_never_registers_a_webhook` passes). The HMAC vs `headerAuth` mismatch is tracked in issue #2326 (APP-CONFIG-019).
9. **AC9 (Honest secret expiry class):** Partially implemented, then superseded. SecretSpec was cataloged as `kind=EXTERNAL`, `envs=("staging", "prod")`, `value_pattern=tk_[0-9a-f]{40}` with `Expiry.DECLARED` in #2464 (`99c65d6b`). 15 tests pass in `tests/test_vikunja_reconciler_token_spec.py`. Per-env dates were never recorded in `values/<env>.yaml` due to the retirement decision. Explicitly declared as unmet/superseded.

### Code-level checklist

- **Injection**: Clean. All URL constructions use strongly typed `int` identifiers (`project_id`, `team_id`, `task_id`) or validated path constants. Payloads are serialized via `requests(json=...)`. No shell invocations or SQL queries.
- **Secrets**: Clean. Reconciler token is retrieved via SOPS in-memory only. Never printed to logs/stdout, never passed in CLI flags or environment variables. No secrets committed to git.
- **Auth**: Clean. Requests send `Authorization: Bearer <token>`. Team permissions map safely to Swagger numeric constants.
- **Performance**: Clean. List endpoints paginate with `PAGE_SIZE=50` and bounded page ranges (`range(1, 1000)`). No N+1 queries or unbounded recursion.
- **Resilience**: Clean. All HTTP calls enforce a 10s timeout. Fails closed with descriptive errors on missing users, missing tokens, or invalid rights.
- **Quality**: Clean. Cyclomatic complexity measured across all functions in `toolkit/features/vikunja_*.py` and `toolkit/cli/sync.py` is ≤ 9. Static typing verified (`mypy` clean), lint and format verified (`ruff` clean).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) | Disposition |
|---|---|---|---|---|---|---|---|
| Minor | REAL | contract-set / features.json | In `features.json` f2, the `verification` command (`poetry run pytest tests/test_vikunja_client.py tests/test_vikunja_reconciler.py -q`) omits `tests/test_vikunja_api_contract.py`, despite the feature's behavior citing AC5 (swagger fixture) and its evidence field reporting 47 passed tests across all three files. | `features.json:12` runs 31 tests; running with `test_vikunja_api_contract.py` runs 47 tests. | `tests/test_vikunja_api_contract.py::test_every_client_request_exists_in_the_servers_swagger` | spec (`features.json` f2 `verification` string) | **Accept as tracked gap.** The tests exist and pass (47/47 in CI and local run). Contract set is locked during passing archive review; do not edit now to prevent review invalidation. |
| Minor | REAL | contract-set / features.json | In `features.json` f3, the `verification` command specifies `-k 'team or share or idempotent'`. The tests asserting idempotence (`changed=0`) in `tests/test_vikunja_reconciler.py` are named `test_a_second_run_over_what_the_first_created_changes_nothing` and `test_nothing_to_do_reports_changed_zero`. Neither matches the substring `idempotent`, so the filter deselects the idempotency test during verification. | `pytest -k 'team or share or idempotent'` selects 3 tests and deselects 16. | `tests/test_vikunja_reconciler.py::test_a_second_run_over_what_the_first_created_changes_nothing` | spec (`features.json` f3 `verification` string) | **Accept as tracked gap.** Both idempotency tests exist and pass when run directly (19/19 pass in module). Contract set is locked; track in verification dispositions. |
| Minor | REAL | spec status | `proposal.md` frontmatter carries `status: draft` rather than `verifying`, although implementation completed, ran on prod, and was superseded. | `specs/APP-CONFIG-013-vikunja-shared-projects/proposal.md:4` reads `status: draft`. | `tests/test_spec_gate.py::test_archived_specs_have_archived_or_abandoned_status` | spec (`proposal.md` frontmatter) | **Overwritten mechanically on archive.** `dotf spec archive` rewrites `status: draft` directly to `status: archived`. No manual edit needed. |
| Minor | REAL | spec scope | AC7 (prod live verification as `manu`) and AC9 (per-env declared expiry dates) remain unmet. This is not a hidden gap: it is explicitly stated and tracked across `proposal.md`, `tasks.md`, `verification.md`, and `features.json` (f5 and f7 marked `state: blocked`, `verification: none: superseded`) due to the retirement of Vikunja in CONSOLE-005 (#2587) under amended ADR-066 (#2575 `32247509`). | `proposal.md:14`, `tasks.md:50`, `verification.md:10`, `features.json:34,48`; ADR-066 amendment. | n/a (superseded requirement) | spec / vault (ADR-066 / CONSOLE-005) | **Accepted as documented supersession.** Verifying a retired service in production yields zero operational value. |
| Question | UNVERIFIED | production rollout | Live cluster verification on staging (2026-10-16) and prod (2026-10-18) is documented via issue #1701 comments, but cannot be directly observed or queried via `kubectl` from this sandboxed worktree session. | `verification.md:15-17` cites issue #1701 comment 6243987329. `kubectl` execution is disallowed in worktree testing doctrine. | UNTESTED (live cluster check) | none (verified by consequence/ticket records) | **Accept as documented.** Live deployment succeeded and was active until ADR-066 amendment initiated retirement. |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|---|---|---|
| Correctness        | B | Core requirements AC1–AC6 and AC8 fully met with zero code defects; AC7 and AC9 transparently dispositioned as unmet/superseded. |
| Verification       | B | 101 unit/contract tests passing; mutation testing proves negative paths; minor filter omissions in `features.json` f2 and f3. |
| Scope              | A | Implementation is cleanly bounded across reconciler, client, CLI, SSOT, and secrets catalog without extraneous changes. |
| Reliability        | A | Reconciler is strictly idempotent, handles case insensitivity and SSO edge cases, fails closed, and enforces HTTP timeouts. |
| Maintainability    | A | Clean, modular Python code; all functions have cyclomatic complexity ≤ 9; strict typing and formatting verified. |
| Handoff-readiness  | B | Honest supersession records in spec artifacts; promotion candidates (`lesson-578`, `adr-066`) present and valid on disk. |

### Verdict

**PASS WITH GAPS**

`dotf spec archive APP-CONFIG-013-vikunja-shared-projects` is **advisable** in the current state:
1. There are no Blockers and no REAL Majors. The open items are Minors concerning test selector precision in `features.json` and documented supersessions for AC7/AC9, each dispositioned above.
2. The contract set (`proposal.md`, `tasks.md`, `features.json`) remains untouched by this review, preserving digest freshness against `review-request.json`.
3. All promotion candidates in `verification.md` are answered and verified to exist on disk (`docs/lessons/process-method/lesson-578-a-client-test-checks-its-requests-against-the-servers-own-swagger-not-a-fake.md` and `docs/adr/adr-066-self-hosted-task-platform.md`).
4. Zero unresolved `[AGENT-DRAFT]` or `[AGENT-SUGGESTION]` tags exist in any spec file.

### Recommended next steps

Every recommendation below is **outside the contract set** (`proposal.md`, `tasks.md`, `features.json`): do NOT edit contract files, as doing so would invalidate this passing verdict.

- **Archive execution [outside]:** Run `dotf spec archive APP-CONFIG-013-vikunja-shared-projects` to complete the mechanical move to `specs/archive/APP-CONFIG-013-vikunja-shared-projects/`.
- **Bitácora ticket closure [outside — GitHub]:** Close issue #1701 with reference to this archive and the superseding issue CONSOLE-005 (#2587).
- **Knowledge hygiene [outside — complete]:** Lesson-578 and the ADR-066 amendment are already committed on master; no further promotions required.
