---
spec: "OPS-038-gitea-forge-upgrade"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "dc6c01d6b3b2dc282f38212854e4d5892afcc6a1"
reviewer: "nan/glm5.3-flash"
date: "2026-10-21"
---

# Adversarial review — OPS-038-gitea-forge-upgrade

**Round**: 2 (re-review after the round-1 dispositions; `review-request.json` carries the contract digests,
recorded at `dc6c01d6` — I did not edit any contract file).
**Scope**: `git diff 30d3be8ce0934eff140fc21b8bf24f3bb6baba72...HEAD` (base stated by the launcher; as in
round 1, the range bundles ~150 merged PRs of other specs' work — 490 files, +22,267/−6,859 — a base-resolution
artifact, not implementer creep; OPS-038's own delta is `c700d08c`, #2379 `809a9269`, #2381 `1bf91076`,
#2384 `f44f557a`, #2408 `2e2587ca`, plus the docs-only archive commits).
**Sources**: `specs/OPS-038-gitea-forge-upgrade/{proposal,tasks,verification,features}.md/json`,
`specs/OPS-038-gitea-forge-upgrade/review-round1.md`, `docs/runbooks/gitea-upgrade.md`,
`docs/lessons/storage-backup/lesson-586-*.md`, `toolkit/features/gitea_upgrade_probe.py`,
`tests/test_gitea_*.py`, GitHub issues #2375/#2619/#2620/#1823/#2063 read live with `gh` (2026-10-21).

## Round-1 dispositions — verified, not taken on faith

Round 1 (FAIL, `nan/qwen3.8-flash`) had two REAL Majors and one THEORETICAL Major. Each claimed fix was
re-checked against the live source, not the disposition text:

| Round-1 finding | Claimed fix | What I verified fresh at HEAD |
|---|---|---|
| Major REAL — AC8 carry named #2063, which does not hold the work | Corrected to #2619 everywhere | `gh issue view 2619`: **OPEN**, "OPS-045: measure that a second push cancels the first Gitea Actions run". Its body holds exactly the work: step 1 adds a `concurrency:` block (group per ref, `cancel-in-progress: true`) to a forge workflow; step 2 is the two-push measurement (queued + executing, recorded with run ids); step 3 notes the result in the runbook §4; it names the runner ≥ 2.0.0 precondition (met since #2425) and cites this spec's round-1 review. The carry target is now valid and actionable |
| Major REAL — AC8, the spec's headline outcome, unmet and unmeasured | Operator decision 2026-10-22: archive with the measurement carried; recorded in `tasks.md` Closing and `verification.md` AC8 | `verification.md` AC8 reads "Not met, carried"; `features.json` f8 is `state: "blocked"` (honest, not `passing`); #2375 — the issue whose title *is* the unmet goal — is **OPEN**, matching `tasks.md`'s "stays open until #2619 lands". The repo has precedent for this shape (#2518 archived OPS-016 "with its unmet criteria carried") |
| Major THEORETICAL — `KNOWN_BASELINE_FAILURES` can widen silently | Ticketed as #2620 (TOOL-124) | `gh issue view 2620`: **OPEN**, body names both unenforced guards with the mutation evidence and the exact tests to add. Re-confirmed at HEAD by my own mutation (below): the premise still holds |
| Minor — f5 said "No ticket tracks this check" | Corrected to #1823 | `features.json` f5 now says "Tracked on #1823"; `gh api …/comments/6331149403` exists and is the carry text |
| Minor — f4/f6/f7 implementer-asserted `passing` | Declined with reasons | Stands as a tracked gap (finding F2 below); I re-confirmed the cited live records (#2375 comments 6230892745, 6238815197, 6231535448) exist and match their summaries |

## What I verified by running (all commands fresh at `670571d6`; contract content unchanged since `dc6c01d6`)

| Claim | Command | Result |
|---|---|---|
| Contract files unchanged since the launcher's request | `git diff dc6c01d6..HEAD -- specs/OPS-038-gitea-forge-upgrade/` | only `review-request.json` (+12) and the 11-line `review.md` placeholder were added by `670571d6`; **no contract file changed** after the recorded sha. (I could not recompute the CLI's digest algorithm from inside the repo — freshness proven by git history instead) |
| "74 passed" | `poetry run pytest -q --no-cov tests/test_gitea_upgrade_probe.py tests/test_gitea_public_url_pin.py tests/test_gitea_drill.py tests/test_gitea_actions_runner.py tests/test_gitea_anonymous_surface.py` | **74 passed** (three fresh runs, incl. under both mutations) — the count in `verification.md` is exact |
| f1's pin, f9's runbook/lesson | `grep -q 'image: gitea/gitea:1.27.3' infra/config/values/common.yaml`; `test -f docs/runbooks/gitea-upgrade.md && find docs/lessons -name 'lesson-*upgrade*.md' \| grep -q .` | both exit 0 |
| Round-1 Major 3 premise still holds | **Mutation**: planted `"Check schema": "planted widening"` into `KNOWN_BASELINE_FAILURES` | all 15 probe tests stayed **green** — reverted; the exclusion set is still unenforced, exactly as #2620 states |
| Round-1 version-floor finding still holds | **Mutation**: reverted the pin to `gitea/gitea:1.25.5` in `common.yaml` | all 74 tests stayed **green** — reverted; the floor the upgrade was bought for is still unguarded, also in #2620 |
| Gate observation | `dotf spec audit` | `[OK] 11 active spec(s), every one tracking an open issue`, exit 0 |
| Draft tags | grep over all four spec files | no `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` |
| Working tree | `git status` | clean apart from my `review.md` |

## Spec and task alignment

- Nine ACs in `proposal.md`; `verification.md` maps each: 7 Met (I confirmed the cited live records and ran
  every executable verification), AC5 **Partial** (merge settings proven; PR-Agent half carried to #1823 —
  comment verified), AC8 **Not met, carried** to #2619 (verified open and holding the work). The record is
  honest about both gaps; nothing is marked met that I could refute.
- `tasks.md` ticks resolve to real commits/PRs (checked in round 1 at `8063633d`; nothing re-ticked since).
- No `risk:` second-signature trigger; no `review: waived`; `dotf spec audit` clean.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | record accuracy | `features.json` f8's evidence **still ends** "Operator decision 2026-10-22: archive OPS-038 and move this half to #2063." — the stale draft round 1 corrected. It contradicts the corrected carry named in the same evidence string ("carried to #2619 (OPS-045), open"), `tasks.md:33/40`, `verification.md:21/36`, and #2619's own body ("the earlier carry to #2063 was wrong"). It also falsifies `verification.md:56`'s round-1 claim "every reference now names #2619" | `features.json:56` vs `tasks.md:33,40` and `verification.md:21,56`; `gh issue view 2619` | UNTESTED (record accuracy) | spec artifacts — `features.json` is contract-frozen under this verdict, so disposition in `verification.md` (correct the "every reference" claim; note f8's last sentence is the stale draft). Any later contract edit re-opens the gate by design |
| Minor | REAL | verification claims | f4/f6/f7 remain `state: "passing"` on non-executable `verification:` strings — implementer-asserted from live records, against the rule quoted in `tasks.md`. Declined in round 1 with reasons (live checks with no command form); the live records themselves are genuine (comments fetched). The CI guard cannot see them: `tests/test_spec_verifications_select_tests.py` matches only pytest commands | `features.json` f4/f6/f7 vs their `verification:` strings | guard covers pytest-shaped commands only | spec artifacts / harness — tracked; stands as declined-with-reason |
| Minor | REAL | guards / quieting | Both durable guards remain unenforced at HEAD: my fresh mutations show a widened `KNOWN_BASELINE_FAILURES` and a reverted 1.25.5 pin both keep the suite green. Round 1's Major (THEORETICAL) is downgraded to Minor **only because** #2620 is open with the exact named tests (`test_the_baseline_exclusions_do_not_widen`, a version-floor test reading the SSOT) — until they land, the drill can pass a corrupt exclusion and the capability AC8 bought can be un-pinned quietly | my two mutations at `670571d6` (both reverted); `gh issue view 2620` | UNTESTED — #2620 names the tests | tests (code + tests, outside the contract set) |
| Minor | REAL | AC5 half | The PR-Agent app (`pragent/pr-agent:0.45.0-gitea_app`) has still not been shown to work against the live 1.27.3 forge; carried to #1823 (comment 6331149403 verified). Adjacent evidence (n8n failure-notice workflow ran against a 1.27.3) suggests the API surface works, but that is not a PR-Agent review | `features.json` f5 `state: "partial"`; `gh api …/6331149403` | UNTESTED against the live forge | ticket #1823 (outside the contract set) |
| Question | — | unreachable | UNVERIFIED from this repo: the drill re-run (needs ace2 + R2), all live-forge checks (OIDC login, `provision changed=0`, PR-Agent), whether any forge (Gitea, not K8s) workflow declares `concurrency` — the "none declares it" claim rests on the runbook/operator record, not on something this checkout can grep — and the archive gate's digest algorithm (implementation outside this repo). None of these are refutable from here; all are recorded on #2375 | — | — | — |

No Blocker. No REAL Major survives round 1: the wrong carry target is fixed and verified live (#2619 holds
the work), and AC8's unmet state is recorded honestly with a valid, open, actionable ticket while #2375
stays open — the outcome round 1's blocking step 1 asked for.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | 7 of 9 ACs evidenced (records fetched, executable verifications pass fresh); AC8 — the stated outcome — unmet and unmeasured, AC5 half-met, both honestly recorded and validly ticketed. |
| Verification       | C | Executable evidence all passes fresh and cited live records are real, but 4/9 features have non-executable `verification:` and 3 `passing` states are implementer-asserted. |
| Scope              | B | OPS-038's own delta matches the proposal; #2425 correctly attributed to OPS-034; the huge range is a launcher base artifact. |
| Reliability        | C | The drill fails closed and rollback is documented, but both guards around it are still unenforced — my fresh mutations stayed green (tracked as #2620 with named tests). |
| Maintainability    | B | Probe functions small and exclusion reasons per-key; the SSOT-literal in `tests/test_gitea_anonymous_surface.py:63` is cosmetic and also named in #2620. |
| Handoff-readiness  | B | Runbook + lesson promoted, dispositions recorded, board matches reality (#2375 open, #2619/#2620 filed); marred only by f8's stale sentence (F1). |

**Aggregation**: no D, three C → floor is PASS WITH GAPS. No Blocker and no REAL Major to escalate it.

### Verdict

**PASS WITH GAPS**

Round 1 failed on two REAL Majors; both are now dispositioned in the way round 1 defined as blocking-clearing,
and I verified each fix against live sources rather than the disposition text. What remains are tracked gaps:
AC8 unmeasured (owned by open #2619 with acceptance criteria), the PR-Agent half of AC5 (#1823), two
unenforced guards with named tests waiting in #2620, and one stale sentence inside f8's evidence (F1) that
must not be mistaken for a live carry.

`dotf spec archive OPS-038-gitea-forge-upgrade` is **advisable** in the current state: the review is fresh
against the recorded contract digests, the verdict is passing, and `dotf spec audit` is clean. Before
archiving, disposition F1 in `verification.md` (non-contract, does not invalidate this review): replace the
"every reference now names #2619" claim with the truth — one stale sentence remains in f8's evidence, naming
#2063, and it is superseded by the corrected carry in the same string.

### Recommended next steps

Contract set is closed under this verdict — route everything below as dispositions in `verification.md`
(applied / ticketed / declined with a reason) or into follow-up tickets.

1. **verification.md (non-contract)** — fix the round-1 disposition claim at line 56 and annotate f8's stale
   final sentence (finding F1). One paragraph.
2. **#2620 (already open)** — land `test_the_baseline_exclusions_do_not_widen` and the SSOT-reading
   version-floor test; until then the drill's exclusions and the 1.27.3 pin are guarded only by a grep string
   and a comment.
3. **#2619 (already open)** — add the `concurrency:` block and take the two-push measurement (queued +
   executing, with run ids); that is the only route to closing #2375, whose title is still the unmet goal.
4. **#1823 (already open)** — record one PR-Agent review run against the 1.27.3 forge to close AC5's open half.
5. Optional: teach `tests/test_spec_verifications_select_tests.py` to flag prose `verification:` strings on
   active specs, so f4/f6/f7-shaped entries cannot tick the "non-vacuous verification command" box silently.

## Closing pass (my own, as reviewer)

- **Debt**: every defect found is in the table above; the two mutation-proven guard gaps are named tests in
  open #2620, not verbal promises.
- **Knowledge**: nothing new to promote beyond lesson-586 (already in `docs/lessons/`); the "verify a carry
  target contains the work with a live query" practice is now exercised twice in this spec's record.
- **Board**: not touched by this run (review-only); #2375 open is the correct state and F1/steps 3–4 are the
  board actions.
- **Review**: no PR belongs to this review run; `review-request.json`'s digests were not recomputed with the
  CLI's algorithm (implementation outside this repo) — freshness instead proven by git history (no contract
  commit after `dc6c01d6`). Marked UNVERIFIED above.
- **Evidence**: all commands and mutations are the tables above, run fresh at `670571d6` in this session; both
  mutations reverted (`git status` clean apart from this `review.md`).
