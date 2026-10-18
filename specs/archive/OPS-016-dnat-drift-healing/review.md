---
spec: "OPS-016-dnat-drift-healing"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "0690f54a924a4b338c66be1e7708c76874c02551"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-18"
---

## Adversarial review

**Scope**: `OPS-016-dnat-drift-healing` — the whole change per the launcher's base: `git diff 68b35a573c4709a61c5a60b142065540c9db3923...HEAD`, judged against the round-1 review (`53d1aa31`, `nan/deepseek-v4-flash`, FAIL) and its late fixes.

**Sources**: `specs/OPS-016-dnat-drift-healing/{proposal,tasks,verification,features}.md|json`; `review-round1.md`; `git diff 68b35a5...HEAD` and `git diff 53d1aa31..HEAD`; `toolkit/features/monitoring.py`; `tests/test_monitoring_{diff,apply_gate,bootstrap}.py`; `tests/test_tailscale_bound_ports_survive_boot.py`; `tests/test_beelink_compose_unit.py`; `tests/test_spec_{gate,verifications_select_tests}.py`; `infra/ansible/roles/{glances,rpi3_services,headscale}/`; `infra/config/uptime-kuma/monitors.json`; `gh issue view` on #963, #2450, #2500, #2501, #2506.

**Diff-scope note.** The launcher's base (`68b35a57`, 2026-08-10) predates ten weeks of unrelated master history: `base...HEAD` measures **883 commits / 2031 files / +201 814 lines**. The spec's own work inside that range is: `f7984634` (#986, proposal), `db436d32` (#992, upsert convergence), `f30711e0` (#999, integration harness), `b27321cc` (#1115, per-role boot-race fix — I verified the commit exists and is titled as `verification.md` claims), plus the two review-application spec commits `53d1aa31` and `0690f54a`. Critically, `git diff 53d1aa31..HEAD` touches **only the spec folder** — the code under review is byte-identical to round 1's state, so round 1's code-level findings carry forward, and I re-ran its load-bearing evidence rather than inheriting it.

### Spec and task alignment

- **Round-1 findings — all six dispositions verified applied or routed (1/6, 2, 3, 4, 5, 6 respectively):**
  1. `features.json` **now exists**, one entry per AC (f1–f6), with executable verification commands for f1/f2/f3/f5 and honest `none: not built` / `none: superseded` for f4/f6. The launcher's `review-request.json` records its digest (`7e3010…`) where round 1's recorded `""`.
  2. The delete-convergence guard gap is **ticketed**: #2506 is OPEN with a title matching the finding exactly ("…can be removed with the suite green, and any read error counts as deleted"). I independently **reproduced the mutation**: replaced the `raise RuntimeError(...)` under `if pending:` at `toolkit/features/monitoring.py:292` with `logger.success(...)` → the three named files still reported **63 passed**; reverted (`git diff toolkit/` empty afterwards).
  3. AC5's `verification.md` row now says plainly what was **not** run ("no off-node probe and no `changed=0` re-run… no test drives their drift branch").
  4. `tasks.md` Closing carries a dated disposition note explaining the unticked boxes.
  5. The delete-path risk now has one state across contract files: `proposal.md` says **RESOLVED 2026-08-11 (#999)**, `tasks.md` Setup says exercised by the same named test, with the non-converging branch explicitly untested (#2506).
  6. AC6 reworded from "met by construction" to **"Superseded … not met"** — a skim can no longer read it as satisfied.
- **AC1 / AC2 / AC3 — re-verified green under my own runs.** `pytest tests/test_monitoring_diff.py -k TestDiffIsNonDestructiveOnASteadyState` → 4 passed; `-k TestDiffMatching` → 6 passed; `tests/test_monitoring_apply_gate.py` → 13 passed; `tests/test_monitoring_bootstrap.py` → 6 passed; all three files together → **63 passed**. The gate files parse the new `features.json` cleanly: `tests/test_spec_verifications_select_tests.py tests/test_spec_gate.py` → **68 passed**.
- **AC4 — honestly unmet.** `grep -in 'glances|agent' infra/config/uptime-kuma/monitors.json` finds only node *descriptions*, no agent-port monitor. `gh issue view`: #963 **OPEN**, #2450 **OPEN**, titles match the amendment's claims.
- **AC5 — narrowed claim checks out in code.** `glances/tasks/main.yml:113–134` compares `len(HostConfig.PortBindings)` vs `len(NetworkSettings.Ports)` and gates `--force-recreate` on `_glances_port_drift` (`:168`); `headscale` role contains **no** `force-recreate` (grep → NONE); `rpi3_services` contains **no** `PortBindings`/`NetworkSettings` check (grep → none) — it does keep a template-change recreate handler (`handlers/main.yml:2`), so "neither the recreate nor the check" reads, correctly in substance, as *no drift recreate and no binding check*; #2500 is **OPEN** with exactly that framing. Live/HTTP evidence remains UNVERIFIED here (finding 3).
- **AC6 — superseded, and the record now says so.** Nothing to test: the fleet sweep was never built.
- **`features.json` gate obligations:** each `passing` entry has non-empty `evidence`; f4/f5/f6 carry `blocked`/`partial`, never `passing`. No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags anywhere in the spec files (the only grep hits are in my own launcher-ted transcript and round 1's quotation of the phrase).
- **`tasks.md` Closing boxes** are all still `[ ]` (finding 4), but each is now dispositioned by the note rather than silently unmarked.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | tests / AC3 delete path | The delete-convergence guard (`monitoring.py:292`) — the one that stops #925's duplicate-monitor class — has no test that makes it fire; the `raise` can be removed with the suite green. The *failure it leaves open* (a future refactor silently dropping the guard, or a non-converging delete reporting success) has never been observed. | My mutation this round: `raise RuntimeError` → `logger.success` → **63 passed** (identical to unmutated), reverted, tree clean. `test_dropping_a_monitor_from_the_seed_deletes_exactly_that_one` only covers the converging case. Ticketed: #2506 **OPEN**, title matches; disposition recorded in `verification.md` §Review dispositions item 2. | UNTESTED — no named test induces a non-converging delete or stubs `get_monitor` to keep returning a deleted id past the deadline | tests (via follow-up #2506 — not in this archive's scope, per the disposition) |
| Minor | REAL | spec contract / process | `features.json` ships `state: "passing"` on f1–f3 although `tasks.md` §Machine-readable features states the **agent CANNOT write `passing` — only the harness, after running `verification`, may**. The file entered the tree in the implementer's own docs commit `0690f54a` ("apply the OPS-016 review"), 3 seconds before the round-2 launcher ran; `dotf spec --help` exposes no verify subcommand and no harness-run artifact records setting them. Mitigant: every `evidence` field is non-empty, and I independently ran all three commands → exit 0 (4 + 6 + 13 tests). | `git show 0690f54a -- specs/…/features.json`; `tasks.md` pass-state gating paragraph; `dotf spec --help` (commands: archive/audit/init/review only) | UNTESTED — no gate checks *who* set a state (`tests/test_spec_verifications_select_tests.py`, 68 passed, validates commands and exit codes only) | spec artifacts — disposition in `verification.md` (record whether a harness run set them; no contract edit demanded under this verdict) |
| Minor | REAL | verification.md | The live claim "`make monitoring-apply CHECK=1` → 0 create, 0 edit, 0 delete (live=36, seed=36) against rpi3" and the Docker-gated integration tests (#999) are assertions I could not reproduce from this worktree; no transcript accompanies them. | `verification.md` AC1 row and §Test status; my run covers only the pytest side. | UNVERIFIED in this round (unit side: the five commands above all passed) | verification.md (evidence) — re-run or link the transcript at archive |
| Minor | REAL | record-keeping | `tasks.md` Closing is uniformly unticked; `verification.md filled in` is demonstrably true, and `Type checks pass` / `Lint passes` were not re-run (justified in the note: the archive changes no code — and I did not run them either). A reader still cannot distinguish "not done" from "done, unticked" at a glance. | `tasks.md` §Closing + its disposition note; `verification.md` is filled (52 lines, per-AC table). | UNTESTED (bookkeeping) | verification.md (disposition — `tasks.md` is contract set and stays untouched under this verdict) |
| Question | — | features.json provenance | Confirm who set `state: "passing"`: a harness run (then record where) or the implementer by hand (then the states are truthful but the gating rule was bypassed this once). | See row 2's evidence; states are factually correct — I ran every command. | n/a | verification.md note or a follow-up ticket |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | AC1–AC3 verified green by my own runs; AC4 unmet, AC5 amended-partial, AC6 superseded — three of six criteria not met as written, openly carried to live tickets. |
| Verification       | B | Every `features.json` verification command ran and passed in this round (40 selected tests + 63-file total + 68 gate tests); the live rpi3 claim and Docker-gated integration remain UNVERIFIED here, and AC5/AC6 now state exactly what was not run. |
| Scope              | A | The archive delta is the spec folder only (`53d1aa31..HEAD` touches nothing else); the range's 201k lines are the launcher's base resolution, not author creep, and the spec's own PRs (#986/#992/#999/#1115) match the proposal one ticket per change. |
| Reliability        | B | Bounded poll raises instead of logging SUCCESS; per-role recreate after the address exists; the two known gaps are ticketed (#2500, #2506); the untested guard is the Major below. |
| Maintainability    | A | Diff extracted into a pure `monitoring_diff.py`; 63 unit tests around apply; comments explain *why* (v2 conditions, cache lag). |
| Handoff-readiness  | B | `features.json` added with one entry per AC, all six round-1 findings dispositioned with live ticket ids, lessons/ADR/promotion answered; Closing boxes remain unticked but are now dispositioned. |

### Verdict
PASS WITH GAPS

No Blocker, and no REAL Major. The one open Major — the delete-convergence guard has no test that can fail it — is tagged **THEORETICAL**: my mutation this round *reproduces the coverage gap* (63 passed with the `raise` removed), but the failure it would allow has never been observed, and it is **ticketed (#2506, OPEN, title matches) with a written disposition**, which is what "tracked" means for this gate. Per the verdict rule, every open Major being THEORETICAL → PASS WITH GAPS; independently, the rubric has one **C** (Correctness — three of six criteria openly unmet) and no D → PASS WITH GAPS minimum. Both paths agree. The UNTESTED test-traceability gate is why this is not a plain PASS: the Major stays open and named, not resolved by claim.

### Recommended next steps

**Contract set — closed.** No edit to `proposal.md`, `tasks.md` or `features.json` is requested; editing one would invalidate this verdict.

**Outside the contract set (disposition in `verification.md` as applied / ticketed / declined):**
- #2506 (already filed): add the named regression test for the delete-divergence branch — a unit case stubbing `get_monitor` to keep returning a deleted id past the deadline, or a Docker-gated case that withholds convergence; the same ticket already owns the `except Exception`-counts-as-deleted problem.
- Record in `verification.md` who set `state: "passing"` in `features.json` (the Question row). The states are truthful — I ran them — but the provenance rule in `tasks.md` deserves one line of audit trail.
- Link or re-run the live rpi3 `CHECK=1` transcript behind AC1's row, or leave it marked UNVERIFIED as AC5 already does.
- Tick (or leave ticking with the existing note) the Closing boxes at archive time; `make type` / `make lint` were not re-run this round either — the note's rationale (archive changes no code) covers it.
- **UNVERIFIED in this run:** the full suite (`make test`), `make type`, `make lint`, the Docker-gated `tests/test_monitoring_integration.py`, and the live cluster claims. I ran the five `features.json` commands, the three-file total (63 passed), the two gate files (68 passed), one mutation (reverted), `gh` on #963/#2450/#2500/#2501/#2506, and the role greps. The working tree is clean apart from this `review.md` and the launcher's own `review-request.json` / round-1 files.

**Verdict: PASS WITH GAPS — `dotf spec archive OPS-016-dnat-drift-healing` is advisable in the current state.** The gaps are tracked with dispositions already on file; the archive gate should accept this review against the recorded contract digests.
