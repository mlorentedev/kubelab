---
spec: "APP-CONFIG-015-n8n-webhook-auth"
verdict: "PASS"
reviewed_sha: "f075e86c148e5773cdac7973459ff3ce2eb18f9b"
reviewer: "nan/mimo-v2.5"
date: "2026-09-27"
---

## Adversarial review

**Scope**: APP-CONFIG-015-n8n-webhook-auth (PRs #1855, #1864, #1873)
**Sources**: `specs/APP-CONFIG-015-n8n-webhook-auth/{proposal,tasks,verification,features}.json`, `git diff 313538fc7190bffa985a303b7cf84a9ab161b133...HEAD`

### Spec and task alignment

All 16 implementation tasks are ticked `[x]`. Every tick has corresponding diff evidence:

- AC1 (forge HMAC): `tests/test_n8n_multi_forge_sync.py` — 10 tests, all passing. The old `$json.rawBody` tests are deleted and replaced with tests that build items from the captured Webhook v2 fixture (`tests/n8n_code_node.py`). The `Parse Forge Event` Code node now reads via `getBinaryDataBuffer(0, 'data')` and uses `crypto.timingSafeEqual` with a length check. The `JSON.stringify(body)` fallback is removed.

- AC2 (Slack HMAC): `tests/test_n8n_slack_capture.py` — 8 tests, all passing. Same pattern: binary fixture, `getBinaryDataBuffer`, `timingSafeEqual`, Slack's `v0:<ts>:<raw bytes>` format preserved. Stale timestamp rejection verified.

- AC3 (IF v2 filter shape): `tests/test_n8n_filter_nodes_v2_shape.py` — 9 tests, all passing. The parametrized test covers every `if`/`filter` node at `typeVersion >= 2`. The four migrated gates are pinned to their original fields. Mutation documented in tasks.md.

- AC4 (signed forge creates task): `tests/test_n8n_probe.py` — 21 tests, all passing. `make n8n-probe` codifies the end-to-end probe. Staging and prod evidence recorded in `verification.md`.

- AC5 (unsigned requests stop at gates): Same probe, plus `make n8n-probe` execution evidence from staging (executions 45-47, 53-55) and prod (executions 198-200).

No unchecked tasks remain. No `[AGENT-DRAFT]` or `[AGENT-SUGGESTION]` tags in any spec file.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | THEORETICAL | secrets | The in-pod `redact` regex misses credentials shaped like `api_key=value` (underscore before `key`) | code read of `toolkit/features/n8n_probe.py` line 206 | `test_the_in_pod_script_redacts_credentials_from_error_messages` (covers the known patterns) | code (lower priority; the slice-to-300 and the `redact` regex cover the patterns n8n HTTP nodes actually emit) |
| Minor | N/A | scope | The diff `313538fc...HEAD` includes 13 commits unrelated to this spec (AUTH-011, BACKUP-055, PR-Agent, DNS hairpin, etc.) — expected because the base predates those PRs, not a code-level scope-creep | `git log --oneline 313538fc...HEAD` shows 13 commits | N/A | — (informational; the spec's own PRs #1855/#1864/#1873 are the correct scope) |

**Deleted tests — retention bar:**

The change removes several old tests. Each removal is justified:

- `test_workflow_node_raw_body_string_and_valid_hmac` — validated a `$json.rawBody` path n8n 2.12.3 never produces (lesson-467). Replaced by `test_gitea_signature_over_the_delivered_bytes_is_valid` which uses the real binary fixture.
- `test_workflow_node_object_fallback_fails_closed_on_non_ascii_payload` and `test_workflow_node_object_fallback_fails_closed_on_differently_formatted_payload` — validated the `JSON.stringify(body)` fallback that is now removed. Replaced by `test_no_raw_bytes_fails_closed_even_when_the_parsed_body_would_match` which confirms the fallback does not return.
- `eval_forge_node` / `eval_slack_node` — the old harness built `$json` by hand. Replaced by `tests/n8n_code_node.py`'s `run_code_node` which provides the exact runtime n8n produces.

All deletions have a stronger replacement that covers the same risk surface with the correct input shape.

### Code-level security checklist

| Category | Verdict | Evidence |
|----------|---------|----------|
| Injection | Clean | Pod script uses parameterized SQLite queries (`db.all(sql, params, cb)`). No string interpolation in SQL. |
| Secrets | Clean | Forge secret read from SOPS into memory; only HMAC goes on the wire. Test fixtures use `"my-secret-key"`. The `redact` regex in the pod script strips credentials from error messages. `test_the_secret_never_reaches_the_log` verifies. |
| Auth | Clean | Both HMAC checks use `crypto.timingSafeEqual` with a length guard before the compare. Fail closed when bytes/secret are missing. Slack timestamp window (300s) preserved. |
| Performance | Clean | No N+1 queries, no unbounded loops, no blocking calls in async paths. |
| Resilience | Clean | `getBinaryDataBuffer` wrapped in try/catch → fail closed. `wait_for_execution` has timeout + ambiguous detection. Probe cleanup sweeps by key when `taskId` missing. |
| Quality | Clean | Functions are short and focused. The `_POD_SCRIPT` is a single parameterized script (JSON request → last stdout line). Comments explain WHY throughout. |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All five acceptance criteria verified with unit + live evidence; negative paths (wrong sig, missing sig, no bytes, stale timestamp, tampered bytes, missing secret) all covered |
| Verification       | A | 80 passing tests with named coverage per AC; `make n8n-probe` output from staging + prod with execution IDs; fixture-capture tied to pinned n8n image version |
| Scope              | B | The diff contains unrelated commits (AUTH-011, BACKUP-055, PR-Agent, DNS) in the HEAD range; the spec's own PRs are correctly scoped (#1855, #1864, #1873) |
| Reliability        | A | Fail-closed on all error paths; timing-safe comparison; credential redaction in pod script; probe cleanup handles missing taskId |
| Maintainability    | A | Clear naming, self-documenting tests, `n8n_code_node.py` harness shared across test files, comments explain non-obvious decisions (why no JSON.stringify fallback, why timingSafeEqual needs length check) |
| Handoff-readiness  | A | Lesson 467 written; verification.md filled with execution evidence; closing checklist complete; PRs merged and referenced |

### Verdict
PASS

### Recommended next steps

All recommendations are tracked, not blocking:

1. **(tests, follow-up)** Consider extending the in-pod `redact` regex to cover `api_key=value` and similar underscored credential shapes. Low priority — the slice-to-300 and n8n's actual error patterns make this unlikely to leak in practice. Disposition: ticket or decline with reason in `verification.md`.

2. **(spec, done)** The `features.json` entries are in `pending` state — this is correct per the pass-state gating rule (only the harness sets `passing`). No action needed; the harness will update state during archive.

`dotf spec archive` is **advisable** in the current state. No blockers or real majors remain. The minor findings are tracked above and do not gate archive.
