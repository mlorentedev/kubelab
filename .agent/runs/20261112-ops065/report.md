# Run 20261112-ops065

- Armed: 2026-11-12, expires 2026-11-12T19:05:42Z.
- Ended: 2026-11-12T12:20Z, reason `queue-empty`: both planned items reached their end state. The next item on this front, #3144 (OBS-065), was excluded at arming: its 7-day window closes 2026-11-13 04:30Z.
- Host: the wake-lock state is not recorded for this run.

## Items

| Item | Outcome | Evidence |
|---|---|---|
| #3076 OPS-065 edge backend timeouts: measure | Done, merged; then Blocked on the owner | #3359 merged at 0f9eb7c: `make edge-slow-routes` (toolkit `obs slow-routes`, 22 tests) and the prod reading in `specs/OPS-065-edge-backend-timeouts/verification.md`. CI failed once on the subprocess-encoding guard (a new test's `git grep`), fixed in 0f9eb7c. |
| #3076 OPS-065: decision | ADR-076 proposed, not merged | #3366 ready for review, triaged; the owner decides (A/B on #3076). |
| #3308 what limits warm capacity | Done, closed | #3362 merged at 8318e33: `MAX_VUS` pool cap, busiest-CPU busy and softirq per timeline row, run `2026-11-12-6fd47188`, report section "What limits warm capacity". `api` healthy to 3,200/s with 1,000 connections (followed the pool's size, not a CPU); `web` limited by one CPU of ace1 (97% at 2,000/s, about 60 points softirq). Load-test tests: 178 passed. |

## Filed

- #3375 why staging's network softirq lands on one CPU (Backlog), the question #3308 left open.

## Knowledge

- lesson-739 (a load generator's connection pool can be the limit it measures).
- Runbook `docs/runbooks/load-test.md`: `MAX_VUS` and the busiest-CPU fields.
- ADR-076 proposed in #3366.

## Merges

#3359 and #3362, each through `dotf pr land` with CI green, CLEAN, a `## Review triage` comment and the PR's triage queue at 0. Reviewed by PR-Agent only; CodeRabbit and Codex posted quota notices. PR-Agent does not re-review below 3 new commits, so #3362's last commits were reviewed on request (`/review`) and #3359's one-line fix was not re-reviewed.

## Waiting on the owner

1. #3366 / #3076: accept ADR-076 as written (A) or change its values or exceptions first (B).
2. Whether the capped warm figure (`api` 3,200/s, `web` 1,600 to 2,000/s) may be quoted; the report keeps the uncapped sentence until then.
