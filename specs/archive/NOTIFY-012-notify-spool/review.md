---
spec: "NOTIFY-012-notify-spool"
verdict: "PASS"
reviewed_sha: "be11baf503f7f75cf5961645538dfd6dd6ac146b"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-30"
---

## Adversarial review

**Scope**: NOTIFY-012-notify-spool, diff `1ee1770f36d4e40564beb9e699614bc5bf02dd45...HEAD`
(the launcher-resolved base = parent of a188c366, verified with `git rev-parse a188c366^`).
**Sources**: `specs/NOTIFY-012-notify-spool/spec.md`, `review-request.json`; implementation in
`infra/ansible/roles/node_notify/` (script template, spool service/timer templates, tasks, defaults);
tests `tests/test_node_notify_dedup.py`, `tests/test_node_notify_role.py`; docs
`docs/lessons/observability/lesson-678-*`, `docs/runbooks/maintenance-timer.md`; commits
a188c366 (#2859), 38c1f081 (#2861), be11baf5 (#2867).

**Scope note (not implementer creep):** the stated base…HEAD range interleaves five unrelated
merged PRs (#2855, #2838, #2858, #2860, #2864) with the spec's own commits — the base is where the
spec's work *starts*, not a spec-only branch. I reviewed the NOTIFY-012 content (script, role,
templates, both test files, spec, lessons, runbook) line by line, and covered the interleaved work
by the full-suite run below rather than an adversarial read of each. Within the spec's files, the
only cross-PR change is the mechanical `encoding="utf-8"` pass of #2864 in the notify tests (no
behavioral edit).

### Spec and task alignment

This spec uses `spec.md` with a checklist (no proposal/tasks/verification triad); the review
request's `contract_digests` are all empty and match `dotf spec digest NOTIFY-012-notify-spool`
exactly, so staleness falls back to `reviewed_sha`, recorded as HEAD.

- No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags in the spec.
- **Checklist verified by running, not by reading claims:**
  - Notify tests: `203 passed, 16 skipped` (ran twice this session); full suite:
    `8400 passed, 19 skipped, 170 deselected in 792s`, 0 failures.
  - Spec claim "mutants red (21)": I reproduced **6 of them myself** with in-place mutations,
    each turning a named test red, then `git checkout`-restored (tree verified clean):
    1. `&& ! kept` dropped from the direct-send check → `test_a_notice_does_not_overtake_one_still_kept` red;
    2. flush's `flock -w` neutralized → `test_a_flush_that_finds_the_spool_busy_leaves_it_to_the_run_holding_it` red;
    3. cleanup gate `length > 0` → `length >= 0` → `test_provisioning_clears_the_notifiers_a_refused_page_left_failed` red;
    4. fold disabled → `test_a_reminder_of_a_page_still_kept_is_folded_into_it` + `test_a_unit_that_keeps_failing_past_the_ttl_still_closes_its_incident` red;
    5. cleanup argv `map('first')` → `map('last')` → `test_the_cleanup_resets_each_unit_the_listing_names` red;
    6. age drop disabled → `test_a_notice_older_than_the_spool_keeps_is_dropped` red.
  - Core ordering invariant argued from the code and matching the spec: a direct send requires
    *lock held + spool empty*, and every window where a notice exists "in limbo" (deliver failing,
    keep writing) is under the spool lock or behind an existing spool file — so a recovery can
    never reach n8n before the failure it closes. The same-unit in-flight case rests on the unit
    lock outlasting one delivery (40 s > 30 s), pinned by
    `test_notify_unit_timeout_exceeds_the_script_retry_budget` (also asserts the spool unit's
    `TimeoutStartSec` contains lock wait + retry budget).
  - Timing claims, ordering, age drop, half-written notice, exercise-not-kept, unit/timer/
    directory/cleanup, `.unreadable-` set-aside, busy-flush exit 0, per-unit fold, cleanup gate
    evaluation: each has a named test, listed in the alignment table below via the checklist —
    traced one by one against `tests/test_node_notify_dedup.py` / `tests/test_node_notify_role.py`.
- **Issue/board claims verified live:** `gh issue view 2866` → NOTIFY-013, OPEN (the clock-gap
  follow-up the spec's Out list points to); `gh issue view 2787` → CLOSED by this work.
- **Test deletions (retention bar):** three tests were deleted
  (`test_the_next_failure_after_a_refused_first_page_is_still_the_first_page`,
  `test_an_undelivered_recovery_leaves_the_failed_page_in_place`,
  `test_a_failed_delivery_does_not_count_as_a_page`) — all three encode the old rule "a refused
  page is not recorded" that this spec *deliberately inverts*. Each has a replacement asserting the
  flipped property (`test_a_page_neither_delivered_nor_kept_does_not_count_as_sent`,
  `test_a_refused_recovery_is_kept_and_closes_the_incident`), the *why* is recorded in
  lesson-644 and the spec checklist, and the flipped behavior is mutant-verified (mutation 1 and 4
  above). Focused command: `pytest tests/test_node_notify_dedup.py`. Fields satisfied; no coverage
  went silently quiet.
- **Prior round dispositions (F1–F12, #2867):** spot-checked F2 (per-unit fold test exists), F3
  (gate evaluated via `task_runs` on empty and non-empty stdout, not string containment), F9
  (spec text now says the busy path exits 0; test exists), F11 (at-least-once in Out list), F6
  (ticketed, confirmed open). F5 remains open by design (see findings).
- **UNVERIFIED:** the ace2 live-provision evidence (timer active, failed notifiers cleared,
  rerun `changed=0` — documented in PR #2861's body) and the live `make maintain-notify-test`
  delivery check (F5) require a real node and a real n8n send; out of reach from this repo.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | THEORETICAL | correctness | A reminder folded into a kept page does not update that page's count: if the *reminder itself* was kept (`KIND=again` title "still failing (N failures)"), later folds renew only the state file, so the page finally delivered understates N in its title | code read: the fold block writes `$STATE_FILE` only; `keep()` writes the payload once | UNTESTED — `test_a_reminder_of_a_page_still_kept_is_folded_into_it` asserts only the file count, never the delivered title's count | code + tests, or a spec line if the frozen count is intended (outside the contract set) |
| Minor | THEORETICAL | resilience (role) | The role's `reset-failed` has no tolerance for a unit vanishing between `list-units` and `reset-failed` (a non-zero `command` fails the play), unlike the script's own reset which logs and continues | code read of `tasks/main.yml` vs the script's `systemctl reset-failed ... \|\| echo` | UNTESTED — race window, no test exercises it | code + tests (e.g. `\|\| true` with logging) |
| Minor | THEORETICAL | resilience (flush) | A backlog of ≥9 notices each taking the full ~30 s delivery budget exceeds the spool unit's `TimeoutStartSec=300` (40 s lock + N×30 s); systemd kills the flush mid-run. No data loss (`rm` only after a successful deliver, at-least-once accepted), and the unit stays failed as the trace, but one run cannot drain such a backlog | arithmetic from the rendered defaults and `deliver()`'s own budget comment | UNTESTED — no large-backlog test | code/tests (raise timeout or bound the backlog) — surface only, converges across timer runs |
| Minor | THEORETICAL | verification | Open item F5: the live delivery check (`make maintain-notify-test` end-to-end through real n8n) was not re-run after the script changed; it was asked of the operator in #2867 | #2867 disposition table | UNTESTED by construction (live path) | verification evidence — operator; outside the contract set |
| Question | — | spec | Spec's ordering bullet ("a notice is sent directly only when it holds the spool's lock and the spool is empty") can be read to cover the exercise path, but the exercise *is* sent direct without the lock. The spec's separate exercise bullet makes this intended; confirm that reading | spec.md two bullets vs the `if [ -z "$KIND" ]` early direct send | `test_exercising_the_path_still_fails_when_nothing_was_delivered` covers the exercise, not the interleave | none needed; noted for the record |

Code-level checklist walked over the diff: no injection (curl config on stdin, argv lists for
systemctl, JSON built in python, unit name validated), no secrets added (token file pre-existing),
no auth surface, no unbounded loops (flush drains a bounded spool; `kept()` is a bounded glob),
no blocking calls in async paths (N/A — systemd oneshots with bounded `flock -w` and curl timeouts).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Every acceptance criterion has a named test and passed in this session's runs; only minor negative-path nits remain (count staleness, role reset race) |
| Verification       | B | Reproducible pytest evidence + 21 mutant claims (6 independently reproduced red here); the live ace2/F5 evidence is documented but not reproducible from this repo |
| Scope              | B | The spec's diff matches spec.md exactly; the base…HEAD range interleaves five unrelated merged PRs chosen by the launcher's base (not implementer creep), plus a mechanical encoding pass in the tests |
| Reliability        | B | Busy-lock, refusal-stop, age-drop, unreadable-set-aside and keep-failure paths all handled and tested; at-least-once is an explicit, documented choice; the reset-failed race is tolerated in the script but not the role |
| Maintainability    | B | Flat early-exit control flow (F12 declined with reason), functions within limits, heavily commented with measured rationale; no dead code found |
| Handoff-readiness  | A | spec.md, runbook, lessons 678/644/647 and a full F1–F12 disposition table all updated in-session; follow-up ticket #2866 open |

Aggregation: no D, no C → all B or above (one A). Severity axis: no Blocker, no Major
(all findings Minor/Theoretical) → **PASS**.

### Verdict

PASS

### Recommended next steps

- (For the implementer to disposition — in the spec checklist/PR record as this repo already does,
  or a follow-up ticket; **not** as edits to any contract file alongside this verdict.)
- F5: run `make maintain-notify-test` against live n8n once and record the result next to the
  ace2 provision evidence.
- Consider rewriting the kept page's count when a reminder folds into it (Finding 1), or add one
  spec line stating the count is frozen at keep time.
- Consider making the role's `reset-failed` tolerant of a vanishing unit, mirroring the script.
- NOTIFY-013 (#2866) stays the gate for giving rpi4 the role (clock-gap Out item) — already open.
