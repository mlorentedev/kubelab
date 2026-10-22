---
spec: "OPS-038-gitea-forge-upgrade"
verdict: "FAIL"
reviewed_sha: "8063633df30811ebe261c8776e075b4ff420a21b"
reviewer: "nan/qwen3.8-flash"
date: "2026-10-22"
---

# Adversarial review — OPS-038-gitea-forge-upgrade

**Round**: 1 (fresh review; `review-request.json` carries contract digests, none of which I edited)
**Scope**: `git diff 30d3be8ce0934eff140fc21b8bf24f3bb6baba72...HEAD` (base stated by the launcher; it is the
commit immediately before `c700d08c` added this spec, so the range also bundles ~130 merged PRs of other
specs' work — see finding S9).
**Sources**: `specs/OPS-038-gitea-forge-upgrade/{proposal,tasks,verification,features}.md/json`,
`docs/runbooks/gitea-upgrade.md`, `docs/lessons/storage-backup/lesson-586-*.md`,
`toolkit/features/{gitea_drill,gitea_upgrade_probe}.py`, `tests/test_gitea_*.py`, GitHub issues
#2375/#2063/#1823/#2467 read live with `gh` (2026-10-22).

## Spec and task alignment

- `proposal.md` declares 9 acceptance criteria; **none of the nine AC checkboxes in `proposal.md` is ticked**,
  while `verification.md` marks 7 of 9 "Met". The durable per-AC state therefore lives only in
  `verification.md`/`features.json`, not in the criterion list the proposal promises. Not fatal (the archive
  command rewrites `status:`), but it is a spec-vs-record drift worth one line (finding S8).
- `tasks.md`: 10 implementation boxes ticked with commit/PR pointers; 2 left unticked (AC5 PR-Agent half, AC8)
  plus 4 Closing boxes. Every tick I could check resolves to a real commit or PR in the range
  (`1bf91076` #2381, `809a9269` #2379, `2e2587ca` #2408, `b2f13282` #2425) — no invented ticks found.
- `proposal.md` has no `risk:` declaration and no `review: waived`; `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]`
  appear nowhere in the contract files (grep over the folder: only inside this run's
  `review-transcript.jsonl`). No second-signature requirement is triggered.
- The headline promise (`## What`: "After this work … A second push to the same branch cancels the first run,
  including a run already executing on the runner") is **not delivered and was never measured**. `verification.md`
  AC8: "Not met, carried". This is the spec's whole `Why`.

## What I verified by running (all commands fresh at `8063633d`)

| Claim in the spec | Command | Result |
|---|---|---|
| "74 passed" for the gitea suite | `poetry run pytest -q --no-cov tests/test_gitea_upgrade_probe.py tests/test_gitea_public_url_pin.py tests/test_gitea_drill.py tests/test_gitea_actions_runner.py tests/test_gitea_anonymous_surface.py` | **74 passed in 1.50s** — the count in `verification.md` is exact. |
| f1/f2/f3/f5 verification commands pass | same files + `grep -q 'image: gitea/gitea:1.27.3' infra/config/values/common.yaml` | pass; the pin is at `common.yaml:1003`. |
| the CI guard over `features.json` | `poetry run pytest -q --no-cov -m integration tests/test_spec_verifications_select_tests.py` | **23 passed** — so the guard is genuinely silent on the four `"none: …"` verifications (finding S3). |
| the probe is wired, not dead code | `grep -rn "run_probes" toolkit/` | `toolkit/features/gitea_drill.py:324`: `ok = ok and run_probes(run, name, admin_user, sorted(restored))` — the drill fails closed on a probe failure. Real mitigation of the "rests on a drill I cannot re-run" risk. |
| the pin and the drill read the same key | `grep -n "image" toolkit/features/gitea_drill.py` | `_ssot()["image"]`/`gitea["image"]` from `common.yaml` — the `tasks.md` claim holds. |
| `PUBLIC_URL_DETECTION` is guarded | mutation: deleted the `GITEA__server__PUBLIC_URL_DETECTION` line from `compose.yml.j2` | `tests/test_gitea_public_url_pin.py::test_the_public_url_detection_is_pinned_to_the_pre_1_26_behaviour` **failed**. Reverted. |
| each broken behaviour fails the drill | read + the suite above | `test_every_broken_behaviour_fails_the_drill[doctor\|mint\|no_issues\|issue\|html_url\|issue_edit\|patch\|not_applied]` — 8 parametrised negatives, plus `test_a_patch_that_answers_2xx_without_applying_is_not_a_pass` (the TOOL-063 failure mode). Strong negative-path coverage. |
| token never printed | `test_the_token_is_only_ever_sent_to_the_scratch_container` | present and passing; secret-handling checklist clean (no hardcoded creds in the diff; `WRITE_SCOPES` is scoped to `write:repository,write:issue`). |
| AC8/AC5 evidence on #2375 | `gh api repos/mlorentedev/kubelab/issues/comments/6230892745` | exists; its text literally reads "Not yet verified: Authelia OIDC login (owner), the runner picking up a job on 1.27 (act_runner 0.2.13), PR create/comment/edit, and **AC8 (two quick pushes on a repo whose workflow carries `concurrency`)**". |
| AC5 carry on #1823 | `gh api …/comments/6331149403` | exists: "Carried here from OPS-038 … nobody recorded a PR-Agent review against the upgraded forge". |
| AC8 carry target #2063 | `gh issue view 2063 --json body,comments,state` | OPEN, **but it is a leaked-job-volumes ticket**: its 3 proposal steps and 4 acceptance criteria never mention workflow `concurrency`, superseded runs, or a two-push measurement; grep over its comments for `concurren\|two push\|two quick\|supersede` → **empty**. |
| board state | `gh issue view 2375` | **OPEN** — the spec's own tracking issue, whose title *is* the unmet goal ("superseded runs are not cancelled"). |

## Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|---|---|---|---|---|---|---|
| Major | REAL | spec goal / AC8 | The outcome the spec exists for is unmet: no measurement that a second push cancels the first run (queued or executing), and per `features.json` f8 + the runbook §4, no forge workflow declares `concurrency` — so the 1.27.3 capability is bought and unused. | `verification.md` AC8 "Not met, carried"; `features.json` f8 `state: "blocked"`; #2375 comment 6230892745 (fetched) lists AC8 among "Not yet verified" | UNTESTED — nothing in `tests/` measures cancellation; `tests/test_gitea_upgrade_probe.py` does not touch Actions | ticket + tests (a two-push probe in a forge repo); spec artifacts if the criterion is to be re-scoped |
| Major | REAL | disposition / DoD "Board" | The carry names a ticket that does not hold the work: `tasks.md`, `verification.md` and `features.json` f8 all say AC8 "carried by #2063 (OPS-034, step 3)". #2063's body is about leaked job volumes and `shutdown_timeout`; **its step 3 is "Optionally report the `Finally` ordering upstream"** and none of its 4 acceptance criteria covers cancellation. A reader of the archived spec will believe #2063 owns the goal and #2375 can be closed; the goal has no actionable ticket | `gh issue view 2063 --json body` + `--json comments` at 2026-10-22 (quoted above); `ls specs/*OPS-034*` → none | UNTESTED | the ticket (GitHub, outside the contract set) — amend #2063 with the measurement step + one AC, **or** correct the disposition in `verification.md` to name #2375 (open, and already the AC8 recording target per the proposal) |
| Major | THEORETICAL | guard / quieting | `KNOWN_BASELINE_FAILURES` can widen silently. Its own comment says "none may be added to quiet a new one", but no committed test pins the set: I added `"Check schema": "planted widening"` and **all 15 probe tests stayed green**, so a future edit can excuse a real schema error and the drill would pass a corrupt migrated database | mutation at `8063633d` (reverted); `grep -rn KNOWN_BASELINE_FAILURES tests/` → no match | UNTESTED — add `tests/test_gitea_upgrade_probe.py::test_the_baseline_exclusions_do_not_widen` asserting the set is exactly `{"Garbage collect LFS"}` with a reason each | tests (code + tests, outside the contract set) |
| Minor | REAL | verification claims | `tasks.md` ticks "Every acceptance criterion has a matching entry in `features.json` … with a **non-vacuous verification command** ✓", yet 4 of 9 entries (`f4`, `f6`, `f7`, `f8`) carry prose that is not a command (`"none: live check; the drill has no network"`, `"none: not measured"`). The CI guard cannot catch it: `tests/test_spec_verifications_select_tests.py` matches only `poetry run pytest …` (its `_PYTEST` regex), so those four are invisible to it — 23 passed | read of `features.json` + the guard's regex + the guard run above | `test_active_specs_carry_pytest_verifications` is a floor over pytest commands only | spec artifacts (contract set) — or widen the guard; tracked, and under a FAIL it is a re-review item |
| Minor | REAL | feature states | `f4`, `f6`, `f7` record `state: "passing"` with evidence that is prose pointers to live checks, against the rule quoted in the same `tasks.md`: "the agent CANNOT write `passing` — only the harness, after running `verification` and capturing exit code 0". With a non-executable `verification`, no exit code exists; the three states are implementer-asserted. (Their live records are genuine where I could reach them — I confirmed the cited #2375 comments exist.) | `features.json` f4/f6/f7 vs their `verification:` strings | UNTESTED | harness / spec artifacts — tracked |
| Minor | REAL | record accuracy | `features.json` f5 states "**No ticket tracks this check**" for the PR-Agent half of AC5; it **is** tracked — #1823 comment 6331149403 (fetched) reads "Carried here from OPS-038 … nobody recorded a PR-Agent review against the upgraded forge", exactly as `tasks.md`/`verification.md` say. The three files contradict each other on the same fact | `gh api …/comments/6331149403` | UNTESTED | spec artifacts (contract set) — tracked; the error is in the safe direction (understates coverage) |
| Minor | REAL | question / assumption | AC5's unanswered risk is a live one: the forge has been running 1.27.3 since 2026-10-17 and `pragent/pr-agent:0.45.0-gitea_app` was never checked against it (`common.yaml:1693` still pins that tag). `proposal.md` names the consequence ("a silent break fails `review-attestation` on every forge PR"). Adjacent evidence suggests the reviewer does answer on 1.27.3 (`tests/test_n8n_forge_review_failed.py` header: the failure-notice workflow "was also run … against a Gitea 1.27.3"), but that is a record about n8n, not about PR-Agent | `grep -rn "1\.27\.3"`; #2375 comment 6230892745 lists PR create/comment/edit and PR-Agent as not verified | UNTESTED (against the live forge; **UNVERIFIED** from this repo — the Gitea server is not reachable here) | the live check on #1823, recorded there — outside the contract set |
| Minor | THEORETICAL | version floor | Nothing pins the *reason* for the bump. Reverting `common.yaml` to `gitea/gitea:1.25.5` kept **all 74 gitea tests green**; the only guard for "≥1.26 or `concurrency` is dead" is the `grep` string inside f1's `verification`. So the capability AC8 depends on can be un-pinned by any later PR without a red test | mutation at `8063633d` (reverted); `grep -rn "1\.26" tests/*.py` → only docstrings | UNTESTED — a floor assertion (`image: gitea/gitea:<v>` with `v ≥ 1.26`, read from the SSOT, not a literal) | tests (non-contract). Note `tests/test_gitea_anonymous_surface.py:63` supplies `gitea_image="gitea/gitea:1.27.3"` as a **literal** rather than reading the SSOT, the exact pattern its own docstring warns about ("a slower version of no test at all"); it is not asserted there, so it is cosmetic today |
| Minor | SPECULATIVE | perf/blast | `docs/runbooks/gitea-upgrade.md` §4 pairs `make sync-platform-json` with `make provision … TAGS=gitea`; if `platform.json` is not committed before provisioning, the node and the mirror disagree for one run. `infra/config/platform.json` is in the range and `tests/test_sync_platform_json.py` exists | code read only; not reproduced | `tests/test_sync_platform_json.py` (not run for this mutation) | none — surface only |
| Minor | REAL | scope of this review | The launcher's base bundles ~130 merged PRs (477 files, +21,771) that are not OPS-038 work (ADR-073, the product registry, vikunja labels, DNS zones, Homepage retirement…). I judged OPS-038's own delta (`c700d08c`, #2379 `809a9269`, #2381 `1bf91076`, #2408 `2e2587ca`, the docs-only HEAD `8063633d`) and did **not** review the other 460 files; this is a base-resolution artifact, not implementer creep | `git diff --stat` vs `git show --stat HEAD` (10 spec files, docs-only) | — | launcher/harness (dotfiles, out of scope here) |
| Question | — | unreachable | UNVERIFIED from this repo: the actual `make backup-drill-gitea ENV=prod` rehearsal on the 1.27.3 candidate (needs ace2 + R2; `verification.md` says it was not re-run), the live 1.27.3 forge (OIDC login, runner registration, `provision … changed=0`), whether **any** forge (Gitea) repo declares `concurrency`, and the archive gate's own pool/staleness enforcement (implementation outside this repo; I observed only `dotf spec archive --help`, which documents the three pre-flights, and `dotf spec audit`, which printed nothing for OPS-038) | — | — | — |

### Strengths that mitigate a documented risk

(Stated only where they answer a `proposal.md` risk, per the skill's guardrail.)

- The `PUBLIC_URL_DETECTION` default change named as a risk is pinned to `legacy` **and** guarded by a named test
  that my mutation proved fails when the pin is removed.
- "Migrations are not reversible" is answered by the runbook's §5 (restore the snapshot, `PRAGMA integrity_check`,
  re-pin, re-provision) plus §3's fresh-backup-before-window ordering.
- The lesson-586 baseline rule (judge the candidate against the deployed version on the same data) is enforced by
  code and by `test_the_lfs_collection_error_the_deployed_version_also_has_is_not_a_failure` — the exclusion is
  keyed on a named check with a measured reason, not on a loosened threshold.
- The TOOL-063 failure mode the proposal worried about ("the endpoint says 200 and the settings are unchanged")
  is closed by `test_a_patch_that_answers_2xx_without_applying_is_not_a_pass`.

## Evaluator rubric

| Dimension | Grade | Rationale (one line) |
|---|---|---|
| Correctness | C | 7 of 9 ACs evidenced, AC8 (the stated outcome) unmet and unmeasured, AC5 half-met; the code that did land works and its tests pass. |
| Verification | C | Rich, mostly reacheable evidence (I confirmed the cited #2375/#1823 comments live), but 4/9 features have non-executable `verification:` and 3 implementer-set `passing` states, against a ticked box claiming the opposite. |
| Scope | B | OPS-038's own commits match the proposal; #2425 (runner 4.1.0) is correctly attributed to OPS-034, not smuggled in; the huge range is a base artifact. |
| Reliability | C | The drill fails closed and is wired into the restore path, but both durable guards around it (the exclusion set, the version floor) are unenforced — mutations to each stayed green. |
| Maintainability | B | `gitea_upgrade_probe.py` is 161 lines, every function ≤25 lines, no dead code, exclusions carry per-key reasons; `_doctor`'s comprehension is dense but small. |
| Handoff-readiness | C | Runbook and lesson are good and committed; the board disposition is wrong (names a ticket that does not hold the work) and the archive checklist's board box is unticked while #2375 is open. |

**Aggregation**: no D, three C → floor is PASS WITH GAPS. Two **REAL** Majors escalate independently → **FAIL**.

## Verdict

**FAIL**

Not because the code is weak — the probe, the drill wiring and the pin are better guarded than most changes in
this range (three of my four mutations produced a red test, and the suite is honest about what it does not cover).
It fails on the two REAL Majors: the criterion the spec exists for is unmet, and the record of where that work
now lives points at a ticket that demonstrably does not contain it.

## Recommended next steps

Route by set, as the skill requires. A FAIL makes contract-set edits the point of the next round.

**Blocking (must clear before archive — either path flips the two REAL Majors):**

1. **Ticket (outside the contract set, cheapest first).** Put AC8's obligation where it can be executed:
   amend #2063 with a step and one acceptance criterion naming the measurement ("two quick pushes to one branch;
   the second run cancels the first, queued and already-running; add a `concurrency:` block to a forge workflow
   so the measurement can be taken at all"), **or** file a dedicated bitácora issue with that root cause. Then
   record the disposition line in `verification.md`. If #2063 gains the step, the sentence in `tasks.md` becomes
   true without touching the contract set.
2. **Or re-scope honestly (contract set → new round).** If the operator's decision is that OPS-038 closes at
   "the server now supports cancellation" and the measurement belongs to OPS-034, then `proposal.md` must say so:
   AC8 moved to `## Out of scope` and `## What` re-worded to stop promising "a second push cancels the first run".
   That is an edit to the contract set, so it invalidates this review by design — re-run
   `dotf spec review OPS-038-gitea-forge-upgrade` afterwards. Note the precedent this repo already uses for the
   shape (#2518 archived OPS-016 "with its unmet criteria carried"), and that it pairs with a *valid* carry target.
3. **Or measure it.** #2063's own precondition is already satisfied (runner `gitea/runner` 4.1.0 ≥ 2.0.0,
   `common.yaml:1571`, `b2f13282`), so the only missing pieces are a `concurrency:` block in a forge workflow and
   the two-push test recorded on #2375. That is the only route to a clean PASS on the spec's own terms.

**Tracked with a disposition in `verification.md` (non-contract; apply, ticket, or decline with a reason):**

4. Add `tests/test_gitea_upgrade_probe.py::test_the_baseline_exclusions_do_not_widen` pinning
   `KNOWN_BASELINE_FAILURES == {"Garbage collect LFS"}` with a reason each — the code comment states the rule, the
   suite should hold it (same argument as the merge-grant "widening must fail a test" doctrine in `AGENTS.md`).
5. Add a version-floor test reading the SSOT (`gitea/gitea:<v>` with `v ≥ 1.26`) so the capability AC8 needs cannot
   be un-pinned quietly; while there, have `tests/test_gitea_anonymous_surface.py` read the pin instead of
   supplying the literal at line 63.
6. In `verification.md`, correct f5's "No ticket tracks this check" — #1823 comment 6331149403 is the ticket — and
   state plainly that f4/f6/f7's `passing` is implement-asserted from live records, since their `verification:`
   cannot produce an exit code. Do not edit `features.json`/`tasks.md` for these two; the archive gate measures
   staleness against them, and on the next round the reviewer is the one who should be quoting them.
7. Close the loop the DoD "Board" check wants: decide explicitly whether #2375 stays open as the home of the
   cancellation goal (it should, if the carry is not put on #2063), and say so on the PR.

**Do not archive from this state.** `dotf spec archive OPS-038-gitea-forge-upgrade` should be refused by the review
gate on the FAIL verdict recorded here; `--force-without-review --reason "…"` is the declared escape and would
record a bypass — I would not take it, because the blocking item is one ticket edit away, not a re-litigated design.

## Closing pass (my own, as reviewer)

- **Debt**: every defect I found is in the table above; none is held verbally. The two guards my mutations showed
  to be unenforced are listed with named tests to add (4, 5).
- **Knowledge**: nothing here is a new cross-project pattern beyond lesson-586 (already promoted). The
  "carry must name a ticket that contains the work, verified with a live query" point is a one-line candidate for
  the repo's `docs/lessons/process-method/` if the owner wants it captured; I did not write it, since this run is
  review-only and the review names it as finding 1/2.
- **Board**: I did not touch it (out of scope for a review run); finding 2 and step 1 are the board action.
- **Review**: `gh pr list --head chore/archive-three-specs` → `[]`; there is no open PR for this branch yet, so
  nothing is waiting to be triaged. The two sibling reviews in this folder (`OPS-030`, `APP-CONFIG-013`) are other
  specs' windows and not mine to sign.
- **Evidence**: the commands and their outputs are the table at the top; each was run fresh at `8063633d`, and
  every mutation I made was reverted (`git status` clean apart from the untracked `review*.json*`/`review.md`
  files this run is required to leave).
