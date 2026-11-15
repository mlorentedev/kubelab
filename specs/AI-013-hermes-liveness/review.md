---
spec: "AI-013-hermes-liveness"
verdict: "FAIL"
reviewed_sha: "8b22f9ec525c716f3c5c5e24cacf43caf16a1706"
reviewer: "nan/glm5.3-flash"
date: "2026-11-14"
---

## Adversarial review

**Scope**: AI-013-hermes-liveness (bitácora mlorentedev/kubelab#2175)
**Sources**: `specs/AI-013-hermes-liveness/{proposal,tasks,verification,features.json}`; `git diff 338fc72f46254ee92d05964bbad6187a4db70b64...HEAD` (10 spec commits of 39 in range; the rest is work merged from master and judged only where it interacts).

### Spec and task alignment

- The proposal's five ACs map to real, behavioral tests in `tests/test_hermes_liveness.py` (26 tests, all passing on HEAD in this run). The probe is tested through a fake Docker CLI, so health/restart/grace branches are behavior, not string matches. Two independent mutations I applied and reverted were both caught: widening `GRACE_SECONDS` 90→900 (2 tests failed) and reintroducing the round-1 absolute-path cleanup bug (1 test failed). The wiring is not vacuous.
- The `review-request.json` contract digests match `dotf spec digest AI-013-hermes-liveness` exactly (features.json, proposal.md, tasks.md; `spec.md` empty as expected for a full spec).
- Task boxes: the claimed `[x] "Lint, type and relevant test suites pass"` (Closing) is **not true of the reviewed tree** — the full suite is red on HEAD (Finding 1). All other boxes have diff or live evidence behind them.
- Round-1/round-2 dispositions verified as applied in code: activation ordering, pause-prediction, full-path artifact removal, `become: true`, `ProtectHome=read-only` + `ReadWritePaths`, top-level `.RestartCount`, 90s/`RestartCount<=1` grace, and the deployment `rescue`. The prior reviews' findings were genuinely implemented, not papered over.
- `infra/ansible/roles/rpi3_services`… `node_notify` templates confirm `kubelab-notify@` / `kubelab-notify-recovered@` exist; `toolkit infra ansible syntax-check` passes ("All 26 playbooks parse"); `shellcheck` and `bash -n` pass on `hermes-liveness.sh`; neighboring suites (`test_agent_stack_role`, `test_hermes_config`, `test_hermes_alerts`) pass 142/142.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Blocker | REAL | knowledge hygiene / suite | The reviewed HEAD fails the repo's own full test suite: `tests/test_lessons_index.py::test_no_two_lessons_share_a_number` — lesson **756** is claimed by both `networking-dns/lesson-756-a-hot-receive-cpu…` (already on origin/master) and this spec's `observability/lesson-756-an-on-demand-liveness-watchdog…`; **757** is double-claimed by `ansible-provisioning/` and `ci-automation/` lessons inherited through the master merge (master has since renumbered one). This spec's lesson is the later lander, so per the test's own rule it must move to the next free number. The spec even carries two commits dedicated to unique numbering (`4fe25d95`, `4aca4ee7`), re-broken by the final master merge (`58ecc18a`) and not re-checked. | Reproduced this run: `pytest -n auto --dist loadfile` → **1 failed, 10675 passed, 96 skipped in 340.98s**; failure text names both collisions; `git cat-file -e origin/master:docs/lessons/networking-dns/lesson-756…` confirms the master occupant. | `test_no_two_lessons_share_a_number` (the failing test itself) | code (docs: rename the observability lesson to the next free number + index, after re-syncing master so the inherited 757 clears) |
| Major | REAL | verification evidence | The green full-suite evidence recorded in the contract is stale for the reviewed sha: `features.json` f5 claims "Final suite 10630 passed/96 skipped" and `verification.md` "10631 passed, 96 skipped", yet `verification.md` also admits "A final full-suite run remains required after the direct AC2/AC4 changes" — and the final master merge added ~50 tests and the red lesson collision after those runs. A reader of the contract would believe the tree green. Because the stale claim lives in `features.json` (contract set), correcting it invalidates this review by design: fix, then re-review. | The two inconsistent counts above vs. this run's fresh result on HEAD (1 failed / 10675 passed). | `test_no_two_lessons_share_a_number` (red on HEAD); no test covers "evidence freshness" — the discrepancy is the evidence | spec artifacts (`features.json` evidence, `verification.md`) — contract set, hence fix → re-review |
| Minor | THEORETICAL | detection window | The probe's startup grace (90s from `StartedAt`, `RestartCount<=1`) is shorter than Compose's own unhealthy window (60s `start_period` + 3×30s retries ≈ 150s). A gateway that becomes healthy between ~90s and ~150s is still `starting` — Compose would not call it unhealthy — but the next 2-minute probe can page a false incident. AC2 declares "at most 90 seconds of grace", so the code matches the spec; the mismatch is between the two declared mitigations in the proposal's risk section. Narrow: provisioning-path starts pause the timer until healthy, so only out-of-band restarts are exposed. | Code read: `hermes-liveness.sh` `GRACE_SECONDS=90` vs `compose-hermes.yml.j2` `start_period: 60s / retries: 3 / interval: 30s`; no repro attempted (needs a live slow start). | UNTESTED (no test covers the 90–150s interplay) | code (align `GRACE_SECONDS` with `start_period + retries×interval`, or document the gap in the runbook); disposition in `verification.md` |
| Minor | THEORETICAL | runbook accuracy | Runbook says that when the timer is enabled mid-session, "`OnUnitActiveSec` makes the first run two minutes after activation". Systemd semantics: on mid-session enable, `OnBootSec=10min` is already in the past, so the first run elapses ~immediately (within `AccuracySec=5s`), not after two minutes. Harmless here — enabling is gated on Docker health — but the runbook text misstates the mechanism the round-1 disposition ("F3") rests on. The observed `LAST/NEXT 21:49:48/21:51:48` schedule shows the 2-minute cadence, not the first-run delay. | Systemd timer semantics + code read of `agent-stack-hermes-watchdog.timer.j2`; no host repro in this run. | UNTESTED | code (`docs/runbooks/hermes-kubelab.md`); disposition in `verification.md` |
| Minor | REAL | housekeeping | The spec folder's `review-transcript.jsonl` retains `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` markers from the timed-out round-2 attempt (11 occurrences), so the vault doctor flags AI-013 as the one active spec with unresolved tags. No contract file carries any tag. | `grep -rln 'AGENT-DRAFT' specs/AI-013-hermes-liveness/` → only `review-transcript.jsonl`; launcher's vault-health line names AI-013. | UNTESTED | none required for the gate (audit artifact, preserved per the round-2 disposition); the curator may exclude transcripts from the tag scan or drop the transcript at archive |
| Question / assumption | THEORETICAL | AC3 coverage | Powering ace2 off was never physically exercised. The structural argument is sound and verified here (no `Persistent`/`OnCalendar` in the rendered timer, no Kuma monitor in `monitors.json`, no dependency edge on the egress unit), and the proposal explicitly scopes a hung host out. Declared limitation, accepted — recorded so the archive reflects it. | `test_on_demand_timer_never_catches_up_a_powered_off_node`, `test_no_external_monitor_or_always_on_dependency_is_added`, `test_unexpected_agent_manager_death_cannot_disable_its_own_detector` — all pass; `verification.md` states "Power-off was not physically exercised". | Named tests above (structural, by design) | none (accepted risk; disposition in `verification.md` already) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All five ACs behave as specified with behavioral tests, mutations caught, live drill evidence; negative paths (crash loop, stopped/missing/invalid, name validation) covered; no feature defect found. |
| Verification       | C | Focused/neighboring suites, lint, ansible parse and idempotence evidence are strong and reproducible, but the recorded green full-suite claim is stale for the reviewed sha and the tree is in fact red. |
| Scope              | A | The spec's 10 commits touch only the watcher wiring, its tests, runbook, lesson and spec folder; the other 29 range commits are merged master work with no interaction on the spec's files. |
| Reliability        | B | Fail-closed probe, bounded grace, pause/rescue lifecycle and idempotent provisioning are all handled; the rescue path is structural-only (deliberately broken provision never authorized), disclosed. |
| Maintainability    | B | Small shell probe (shellcheck-clean), table-driven behavioral tests, pinned regression tests for each prior review fix; runbook explains the WHY of every sandboxing directive. |
| Handoff-readiness  | B | Runbook, lesson and spec artifacts updated in-session; but the lesson artifact itself currently breaks the repo's numbering contract, and one task box claims suite-green falsely. |

### Verdict
FAIL

### Recommended next steps

- **Code/docs (free set):** after re-syncing with origin/master (whose tip has already renumbered the `ci-automation/lesson-757`), move `docs/lessons/observability/lesson-756-an-on-demand-liveness-watchdog…` to the next free number and update `docs/lessons/observability/_index.md`, per the rule `test_no_two_lessons_share_a_number` itself states (first-landed keeps the number). Re-run the full suite and record the fresh counts.
- **`verification.md` (free set):** replace the stale full-suite figures with the post-merge green run, and add one-line dispositions for the Minor findings above (90s-vs-150s window, runbook timer wording, transcript tag noise).
- **`features.json` (contract set):** its f5 evidence line cites the stale suite count; correcting it is a contract edit and therefore requires the next review round — that re-review is the mechanism, not an inconvenience.
- No Blocker or Major was found in the watcher's runtime behavior itself: the detection contract, lifecycle handling and test fabric are sound. The failure is suite hygiene + evidence freshness on the merged tree.
