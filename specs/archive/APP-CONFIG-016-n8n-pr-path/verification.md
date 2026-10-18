---
tags: [spec, verification, templates]
created: "2026-09-27"
---

# Verification - APP-CONFIG-016-n8n-pr-path

## Evidence

- [x] AC1 (exact-key search on every item shape, fails on a failed search) -> commit `02d0c667`; `tests/test_n8n_pr_path.py::test_the_exact_task_is_found_on_every_shape`, `test_a_longer_key_is_not_a_match`, `test_no_results_is_no_task`, `test_a_failed_search_fails_the_run_rather_than_reading_as_no_task`
- [x] AC2 (only forward events write) -> commit `02d0c667`; `test_only_forward_moving_pull_request_events_write` (10 payloads), `test_an_unsigned_merge_writes_nothing`, `test_a_keyless_merge_writes_nothing`, `test_the_graph_routes_only_tracked_events_to_the_search`, `test_only_a_merge_reaches_the_state_write`
- [x] AC3 (no event read from a response) -> commits `77091a87` (red), `02d0c667` (green); `tests/test_n8n_event_reads.py`, slack `xfail(strict)` against #1877. Mutation: restoring `$json.taskId` in `Append PR URL Comment` turned it red
- [x] AC4 (no dead `options.continueOnFail`) -> commits `77091a87`, `02d0c667`; `tests/test_n8n_http_error_handling.py`, slack `xfail(strict)` against #1877. Mutation: re-adding the option turned it red
- [x] AC5 (write keeps the task) -> commit `02d0c667`; `test_the_update_body_is_the_task_with_only_done_changed`, `test_the_writes_read_the_event_from_the_extractor`
- [x] AC6 (signed merge probe, staging) -> commit `a5b54762`; `tests/test_n8n_probe.py` (7 new tests); live `make n8n-probe ENV=staging` on 2026-09-27 after `make import-n8n ENV=staging` from this branch: `signed forge merged PR (APP-CONFIG-016 AC6): task 9 done, description intact, PR comment present`, all six probes ok, `n8n webhook probe passed`. **Prod, 2026-10-18:** `make n8n-probe ENV=prod` exit 0 against the workflows the operator imported on 2026-10-16 (#2318): `signed forge merged PR (APP-CONFIG-016 AC6): task 35 done, description intact`, `n8n webhook probe passed`. The probe deletes its own tasks

## Test status

- Test suite: `make test-fast` -> 2953 passed, 15 skipped, 3 xfailed; the only 3 failures were the lesson counters, fixed on master by #1875 and green after rebasing on it. `make lint` and `make type` exit 0
- Manual smoke test: none by hand; the staging probe is the end-to-end check, and it creates, merges, reads back and deletes its own tasks
- No regressions in existing test suite: yes

## Decisions made during implementation

- A failed PR-path search halts the run instead of answering through a 502 node (proposal amendment): the forge gets the same non-2xx, and the error stays in n8n's execution record
- The notice after the writes halts on error, as the create path's does: a failed delivery for a landed write is visible, a silently missed notice is not. A manual redelivery would add a second comment
- The merge probe mints `PROBE-MERGE-<epoch>`, its own AREA, so its key can never equal the issue probe's in the same second; the unit test runs that exact shape through `Parse Forge Event`
- Comments are read from `GET /tasks/{id}/comments` rather than `expand[]=comments`: one documented endpoint, no expand semantics
- agent-dispatcher's `Respond 200` read `$json` after an HTTP node; the class guard found it and it was fixed in scope (one expression)

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/ci-automation/lesson-478-after-an-n8n-http-node-json-is-the-response-not-the-event.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the forward-only rule applies ADR-066 D4 as written; nothing here amends it
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: n8n runs only in kubelab

## Review dispositions

Review `review.md` (nan/glm5.3-flash, PASS, reviewed `01504607`):

1. The Evidence lines cite pre-squash SHAs (`77091a87`, `02d0c667`, `a5b54762`) that no longer
   resolve: noted, not rewritten. #1885 squash-merged them as `11659c28`, which is the durable
   reference for all six criteria. The named tests carry the traceability.
2. `features.json` evidence was captured at `34a5e789`, not the reviewed HEAD: answered. The review
   re-ran every feature's verification command at `01504607` and got 96 passed. Neither commit in
   between touches n8n.
3. The launcher's diff spans merged master history, and later specs (#2319, #2349) added the
   Doing-bucket move: no action. The attribution note stands in `review.md`.
4. A title such as `TOOL-035-legacy` would match key `TOOL-035`: declined. Keyed titles follow
   `AREA-NNN: title`, and the not-a-digit rule covers the case that occurs. Revisit only if that
   convention changes.
5. A redelivered signed `opened` event adds a second comment: accepted risk, recorded in the
   proposal's Risks.

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived`
- [x] Folder moved: `specs/APP-CONFIG-016-n8n-pr-path/` -> `specs/archive/APP-CONFIG-016-n8n-pr-path/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [x] Promotions above executed (if any)
