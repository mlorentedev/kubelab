---
spec: "TOOL-035-gitea-repository-reconciliation"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "aba5d89c1e1c01d9856089a1ef5ea175a8fc66bd"
reviewer: "nan/glm5.3-flash"
date: "2026-10-18"
---

## Adversarial review

**Scope**: TOOL-035-gitea-repository-reconciliation
**Sources**: `specs/TOOL-035-gitea-repository-reconciliation/{proposal,tasks,verification}.md`; diff `34a763b9...aba5d89c` (base resolved by the launcher, 2026-08-31 → HEAD 2026-10-18)

### Diff-scope note (stated, not hidden)

The repo is trunk-based with squash merges, so `base...HEAD` spans **all** master activity in the
window (1,398 files, ~134k insertions — every PR merged since 2026-08-31), not only this spec's
work. The spec-attributable surface inside that diff is what this review examined:
`toolkit/features/gitea_{repos,client,tokens,actions_secrets,git,drill}.py`,
`tests/test_gitea_*.py`, `tests/infra/test_gitea_*_live.py`, the `beelink_services` compose
template and `act-runner` config, `docs/lessons/ci-automation/lesson-598`, and the three spec
artifacts. Unrelated trunk work merged in the same window is out of scope for this verdict.

### Spec and task alignment

- AC1–AC7 are all ticked in `proposal.md` with pointers into `verification.md`; the pointers
  resolve (AC1/AC4 prod transcript, AC3 counts table, AC5 both-halves transcript, AC6 accepted-loss
  table + run 9, AC7 `changed=10`→`changed=0`).
- **tasks.md contradicts proposal.md on PR3 and Closing**: all four PR3 tasks and the entire
  Closing section read `[ ]`, yet AC6/AC7 are ticked with evidence. The substance exists in the
  diff — `GITEA__actions__ENABLED: "true"` is declared in `compose.yml.j2:121` (PR3 task 1's
  deliverable), `act-runner-config.yaml.j2` and the runner tests exist, PR #1597 is in the range —
  so the boxes are stale rather than the work missing. Finding 1.
- `features.json` does not exist in the spec folder, while the Closing checklist requires a per-AC
  entry. The repo's own guard (`tests/test_spec_verifications_select_tests.py`) globs
  `*/features.json` and tolerates absence, and the launcher's contract digests record
  `features.json: ""` — so the archive gate will not refuse on it. Finding 2.
- Verification evidence is unusually honest about its own gaps: AC1's lost first-run transcript and
  the issue-count baseline error (lesson-408) are recorded as failures of the verification process,
  not smoothed over.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec artifacts | `tasks.md` PR3 (all four tasks) and the entire Closing section are unticked `[ ]` while `proposal.md` ticks AC6/AC7 with evidence; the deliverables are present in the diff (compose actions switch, act-runner config, PR #1597), so the record understates the shipped state | read of `tasks.md` vs `compose.yml.j2:121`, `templates/act-runner-config.yaml.j2`, `git log` #1597 | UNTESTED (spec record, no test can bind prose) | spec — **contract-set mechanics apply**: editing `tasks.md` after this review invalidates it, so either re-review after ticking, or record the disposition in `verification.md` |
| Minor | REAL | spec artifacts | `features.json` absent while the Closing checklist requires a per-AC entry with a non-vacuous verification command | `ls specs/TOOL-035-*/` shows no `features.json`; `tests/test_spec_verifications_select_tests.py:81` globs only existing files, so CI does not catch the absence | `tests/test_spec_verifications_select_tests.py` (covers presence-quality, not absence) | spec — same contract-set caveat as Finding 1 |
| Question | REAL | ops / credentials | The GitHub migration PAT expires **2026-10-27** (9 days after this review). AC5's work is done for `resume`, but the declaration also names `openkm-brain` (`migrate_from: github:…`) — a migration attempted after expiry fails with an unnamed-credential error path rather than a pre-flight warning | `verification.md` AC5: "token expiration header: 2026-10-27"; `common.yaml` org declaration carries `openkm-brain` | `tests/test_secret_expiry_lookup.py` (the expiry control that surfaced the per-env lookup bug) | code/tests (pre-flight expiry check before a migration run) or a disposition ticket |
| Minor | REAL | verification | AC1's first-run half has no durable evidence — the 2026-09-01 creation transcript was lost and the gap is stated rather than papered over; AC1 stands on the convergence run plus PR2's first `--apply` | `verification.md`, "The first-run half of AC1 is a stated gap" | live transcript (not re-runnable by this reviewer) | spec (`verification.md`) — recorded honestly; no action beyond acknowledging it as a gap that cannot be closed retroactively |
| Question | REAL | verification | AC3/AC5/AC6/AC7 live evidence (165/165 PRs, six green jobs on run 9, `changed=10`→`changed=0`, both-halves token probe) rests on recorded transcripts and #1076 comment links. This reviewer has no forge/GitHub credentials and could not re-run any of it; the claims are accepted on citation, not independently reproduced | `verification.md` transcripts; comment URLs in proposal AC6/AC7 | named live suites exist (`tests/infra/test_gitea_runner_registered_live.py`, `tests/infra/test_gitea_anonymous_surface_live.py`) but were not run here | none — stated limitation of this review round |

**Adversarial pass — what I tried to break and could not:**

- **Deletion safety.** `ReconcilePlan` carries no deletion field (`gitea_repos.py:526`), asserted
  structurally by `test_the_plan_has_no_deletion_field` over `dataclasses.fields`, and `execute`'s
  docstring plus body confirm "Nothing here deletes." The only `delete_repo` in the client is
  gated to the superadmin basic-auth path and the declaration check (`drop-empty` refused
  `personal/zz-stray` live, recorded in verification.md). Could not construct a plan path that
  removes a repository.
- **Privilege creep.** `actor_for_org_creation() is Actor.SUPERADMIN` is encoded as a function the
  tests bind to; the admin token's scope set is *derived* from `SCOPE_BY_METHOD` (a method cannot
  enter the client without its scope entering `REQUIRED_ADMIN_SCOPES`), with mutation evidence for
  all four guards recorded. The standing-DELETE concern that blocked granting `write:repository` is
  respected — migration goes through explicit basic-auth `migrator`, refused per-repo when absent
  (`gitea_repos.py:2046`).
- **Secret handling.** Migration token is passed as `auth_token` body field, never inside
  `clone_addr`, so it cannot persist in the stored remote or surface in an address-echoing error.
  No secret value appears in any transcript in `verification.md` (prefix-comparison explicitly
  noted for the Headscale key check).
- **Idempotence / pagination.** `_paginate` terminates on a short page and joins query strings with
  `&` (the second-`?` latent defect is fixed and guarded by `tests/test_gitea_client_pagination.py`).
  `ensure_team` reads the team back and asserts `can_create_org_repo`/`units_map` rather than the
  coarse `permission` field Gitea reports as `none` on correct teams.
- **Fresh verification run by this reviewer:** `pytest` on the seven spec-relevant test files →
  **224 passed** (9.56s); `ruff check` and `mypy` on `gitea_repos.py`/`gitea_client.py` → clean.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All seven ACs evidenced with named artifacts and negative paths (undeclared-repo reporting, both-halves token probe, no-deletion structural test); AC1's first-run half is a stated gap |
| Verification       | B | Reproducible commands and mutation-verified guards throughout; live claims cited but not independently re-runnable by this reviewer |
| Scope              | B | The reconciler grew well past the proposal (webhooks, review teams, settings, tokens — TOOL-080/TOOL-062/TOOL-078 layering on the same module); each growth is documented and separately spec'd, but the proposal's "teams/webhooks out of scope" line now describes only the original slice |
| Reliability        | A | Failures collected not aborted, failed-org cascade quarantined, migration timeout isolated at 600s, plan-only default with opt-in `--apply` |
| Maintainability    | B | ruff/mypy clean, CC within the repo's C901 bar, derivation-over-literal discipline; `gitea_repos.py` at 2,213 lines is large but sectioned |
| Handoff-readiness  | C | `tasks.md` PR3/Closing unticked against ticked ACs, `features.json` absent, archive checklist open — the record understates the shipped state |

### Verdict

**PASS WITH GAPS** — no Blockers, no REAL Majors; four Minors/Questions, all tracked above with
dispositions. Rubric has one C (Handoff-readiness) and no D.

### Recommended next steps

*(Contract set is closed by this verdict — route these through `verification.md` dispositions or
follow-up tickets, not edits to `proposal.md`/`tasks.md`/`features.json`, which would invalidate
this review.)*

- Disposition Finding 1 in `verification.md`: state that PR3/Closing boxes in `tasks.md` are stale
  relative to the ticked ACs, and that the compose/runner diff is the evidence of record.
- Finding 3: before any `openkm-brain` migration, either reissue the GitHub PAT or ticket the
  expiry as a pre-flight check on the migration path (`migrate_repo` could refuse with
  "credential expires in N days" before spending a 600s call).
- Findings 2 and 4 require no action beyond the dispositions above; Finding 5 is a standing
  limitation of every round that reviews this spec without forge credentials.

### Verdict mechanics

(a) **Verdict: PASS-WITH-GAPS.** (b) `dotf spec archive` is **advisable** in the current state —
the gate's own pre-flights (fresh passing review, contract digests, no `[AGENT-DRAFT]` tags —
none present) are satisfied, with the Minors above carried as dispositions. (c) N/A — no FAIL, no
minimum flip set.
