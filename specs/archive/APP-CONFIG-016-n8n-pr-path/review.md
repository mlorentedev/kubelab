---
spec: "APP-CONFIG-016-n8n-pr-path"
verdict: "PASS"
reviewed_sha: "01504607ce3ec09d78ff9d797e1b380aab03210f"
reviewer: "nan/glm5.3-flash"
date: "2026-10-18"
---

## Adversarial review

**Scope**: APP-CONFIG-016-n8n-pr-path — the PR path of `multi-forge-sync` (search, exact-key match, forward-only writes, event reads, dead `continueOnFail`, live probe).
**Sources**: `specs/APP-CONFIG-016-n8n-pr-path/{proposal,tasks,verification,features.json}`; `git diff a8f0ba9aa6cbc60ef73e85f824aa27bd811ec45a...HEAD`. The spec's own change is squash commit `11659c28` (#1885); the launcher's base spans 349 commits / ~83k lines because the branch carries merged master history — see Scope finding below. `review-request.json` (SDD-042) present with contract digests.

### Spec and task alignment

- All 6 acceptance criteria map to named tests; every named test was run fresh at HEAD: `pytest tests/test_n8n_pr_path.py tests/test_n8n_event_reads.py tests/test_n8n_http_error_handling.py tests/test_n8n_probe.py` → **96 passed**, matching the `features.json` evidence line.
- Tasks.md implementation boxes all carry diff evidence; the closing checklist is only unticked on items that are the archive step itself.
- The proposal's amendment (failed search halts instead of a 502 node) is implemented and stated in both proposal and verification.md — consistent.
- Rejection answers match the proposal table: `Respond 200` emits `{status: "no-task"|"ignored", taskKey}`; the success path has its own `Respond PR Synced` with `status: "linked"|"done"`, `taskKey`, `taskId`.
- The In-Review→Doing bucket-move chain present in the current workflow is **not** this spec's work: it landed in `0b4366a3` (#2349, its own spec) after this change merged. Not counted against APP-CONFIG-016.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | traceability | `verification.md` cites pre-squash commit SHAs (`77091a87`, `02d0c667`, `a5b54762`) that no longer resolve after the #1885 squash merge; only the squash commit `11659c28` is reachable | `git rev-parse 77091a87` → fatal, unknown revision (run in this session) | Traceability survives via named tests + `11659c28`; UNTESTED as a link, none needed | verification.md (outside the contract set — disposition there) |
| Question | REAL | features.json | `state: "passing"` on f1–f5 carries evidence recorded against master `34a5e789`, not HEAD `01504607`; tasks.md says only the harness may set `passing` | `git log --oneline` shows `01504607` and `93df9e6b` after `34a5e789`; neither touches n8n | Mitigated: the features.json verification commands were re-run fresh at HEAD in this review and all pass (96 passed, 0 failed) | verification.md (record the HEAD re-run) |
| Minor | REAL | scope | The launcher's `base...HEAD` diff is 349 commits / ~83k lines of merged master history, not this spec's diff; follow-on commits (#2319, #2349) added behaviour the proposal lists as out of scope (Doing-bucket move on `opened`) under their own specs | `git log --oneline a8f0ba9..HEAD \| wc -l` = 349; `0b4366a3` = "an opened pull request moves its task to the Doing bucket (#2349)" | `tests/test_n8n_doing_bucket.py` belongs to #2349's spec | none (attribution note for the archive record) |
| Minor | SPECULATIVE | correctness | The exact-key rule is "title starts with key and next char is not a digit", so a task titled `TOOL-035-legacy` would match key `TOOL-035`; keyed titles follow the `AREA-NNN: title` convention, so never observed | Code read of `Extract Matched Task ID` in `multi-forge-sync.json` | `test_a_longer_key_is_not_a_match` covers the digit case; the hyphen case UNTESTED | tests (add a hyphen-suffix payload if the convention ever changes) |
| Minor | SPECULATIVE | resilience | A redelivered signed `opened` event adds a second comment; the create path's search now continues on error, so a 401 there reaches `searchFailed` handling rather than halting — behaviour change declared in the proposal and covered by its own branch tests | Proposal "Risks"; diff of `Find Task for Issue`/`Resolve Vikunja Project` (`onError: continueRegularOutput`) | Create-path branch tests in `tests/test_n8n_issue_creates_task.py`; redelivery itself accepted in proposal, UNTESTED | none (accepted risk, proposal-recorded) |

Guard strength was verified by mutation in this session, each reverted (`git status` clean after):

- Re-adding `options.continueOnFail` to `Update Vikunja Task State` → `test_no_http_node_declares_error_handling_where_n8n_never_reads_it[multi-forge-sync]` **failed** (AC4 guard bites).
- Reverting `Append PR URL Comment` to read `$json.taskId` → `test_no_node_reads_the_event_from_a_response[multi-forge-sync]` **failed** (AC3 guard bites).
- Relaxing the not-a-digit rule → `test_a_longer_key_is_not_a_match` **failed** (AC1 exact-key guard bites).
- `slack-task-capture` is `xfail(strict=True)` in both guard files (AC3, AC4) against #1877.
- `ruff check` on all touched test/probe files: all checks passed.
- AC6's live probe (`make n8n-probe ENV=staging`) was **not** re-executed by this review — it fires signed webhooks at a live cluster; the recorded staging (2026-09-27, task 9) and prod (2026-10-18, task 35) evidence stands, and the probe's 7 unit tests pass at HEAD. Live re-execution left to the operator at archive time if desired.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All six criteria verified fresh, negative paths covered, three mutations confirmed the guards fail when the defect is reintroduced |
| Verification       | B | features.json commands are reproducible and re-run green; the AC6 live probe is evidence-recorded but not reproducible by a reviewer without the cluster |
| Scope              | B | This spec's commits match the proposal exactly; the wide diff window is merged master history, with out-of-scope behaviour correctly attributed to later specs |
| Reliability        | A | Failed search halts loudly, error items throw, writes fail loudly, move is confirmed against the stored bucket; races and redelivery accepted in writing |
| Maintainability    | B | jsCode blocks are long but commented with WHY and incident references; guard tests parametrise over every workflow file |
| Handoff-readiness  | A | Lesson promoted to `docs/lessons/`, verification.md filled, #1692 closed with evidence, #1659 left open with the remainder named |

### Verdict
PASS

### Recommended next steps
- In `verification.md` (contract set is closed; this file is outside it), record that the features.json verification commands were re-run at HEAD `01504607` by this review, and note the pre-squash SHAs are unreachable — `11659c28` is the durable reference.
- Disposition the `features.json` state-provenance question (evidence sha `34a5e789` vs HEAD) as harness-captured or re-captured.
- Carry the `TOOL-035-legacy` hyphen-suffix edge into a follow-up ticket only if the task-title convention ever changes; no action now.
- Optionally re-run `make n8n-probe ENV=prod` at archive time to refresh the live evidence; not required by this verdict.
