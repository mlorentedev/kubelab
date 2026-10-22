---
tags: [spec, tasks, templates]
created: "2026-10-16"
---

# Tasks - OPS-038-gitea-forge-upgrade

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from main: `feat/OPS-038-gitea-forge-upgrade` ✓ 2026-10-17 (the work landed through #2379 and #2381)
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-10-17 (#2376)
- [ ] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

> PR 1 is the rehearsal (image pin on a branch, drill, probes); PR 2 is the live upgrade. No live change before the rehearsal is green and the peers have the window.

- [x] [AC1] Pin the candidate image `gitea/gitea:1.27.3` in `common.yaml`; extend `tests/test_gitea_actions_runner.py` or the version-pin test so the pin and the drill read the same key ✓ 2026-10-17 (#2381, `1bf91076`; `tests/test_gitea_anonymous_surface.py` and `tests/test_gitea_public_url_pin.py` read the same pin)
- [x] [AC1] Run `make backup-drill-gitea ENV=prod` from the branch (candidate image on the restored snapshot, no network); record the outcome ✓ 2026-10-17 (baseline on 1.25.5 and candidate on 1.27.3, both passed; recorded on #2375)
- [x] [P] [AC2] Add `PUBLIC_URL_DETECTION` to the templated `app.ini` and run `gitea doctor check --all` inside the drill container; fail on any deprecated key ✓ 2026-10-17 (#2381 pins `legacy`; the doctor probe is #2379, `809a9269`)
- [x] [P] [AC3] Write the API contract probe (issue comment, issue and pull create/edit) and run it inside the drill container with a token minted there ✓ 2026-10-17 (#2379, `809a9269`)
- [x] [P] [AC4] Probe the OIDC callback and `update-oauth --id N` against the restored copy ✓ 2026-10-17 (checked on the live forge instead, because the drill has no network: #2375 comment 2026-10-17T08:05, and `update-oauth` runs inside `TAGS=gitea` provisioning)
- [ ] [AC5] Probe the repo `PATCH` merge settings with the `ensure_settings` read-back, and the PR-Agent app against the scratch server -- **partly done 2026-10-17**: merge settings read-back proven (#2379); the PR-Agent app against 1.27.3 was never recorded. See the disposition under Closing
- [x] [AC6] Check `generate-runner-token` and act_runner 0.2.13 against the scratch server; if it fails, sequence OPS-034 first ✓ 2026-10-17 (run 1521 succeeded on act_runner 0.2.13 against 1.27.3, #2375 comment 2026-10-17T18:43; OPS-034 then moved the runner to 4.1.0, #2425)
- [x] [AC9] Write `docs/runbooks/gitea-upgrade.md` (rehearsal, rollback by snapshot restore, window) and a lesson ✓ 2026-10-17 (#2381; lesson-586)
- [x] [AC7] Tell `review-cli-119-8d`, `feat-2550-lane-reconcile-47`, `fix-bug-sweep-fc` the window; fresh `make backup-node NODE=bee ENV=prod`; `make provision NODE=bee ENV=prod TAGS=gitea`; re-run for `changed=0` ✓ 2026-10-17 (the peer notice itself was not recorded anywhere; the backup, provision and re-run were: snapshot `13893d74`, `changed=4` then `changed=0`, #2375 comment 2026-10-17T06:52)
- [ ] [AC8] Measure the cancellation live with two quick pushes; record on #2375; add `concurrency` to forge workflows if none declares it -- **not done; carried by #2063 (OPS-034 step 3), 2026-10-22**

## Closing

> Disposition 2026-10-22: archived by operator decision after the live upgrade to Gitea 1.27.3 (2026-10-17). Boxes left unticked:
> - **No open questions left in the proposal** (Setup): all but one were answered by the rehearsal and the live upgrade. The open one is whether the PR-Agent app works against 1.27.3 (see AC5 below).
> - **AC5 probe, PR-Agent half** (Implementation): the merge-settings read-back is proven (#2379), the PR-Agent app was not checked against the 1.27.3 server and no later comment on #2375 records it. Carried to #1823 (issuecomment-6331149403), the forge reviewer ticket.
> - **AC8 measurement** (Implementation): carried by #2063 (OPS-034, step 3), open. The runner is now `gitea/runner` 4.1.0 (#2425), which meets the Runner >= 2.0.0 precondition for cancelling a running job, but the two-push measurement was never taken. "Add `concurrency` to forge workflows if none declares it" travels with it: none does.
> - **Every acceptance criterion covered by at least one test**: AC2, AC3 and the merge-settings half of AC5 have unit and drill tests; AC4, AC6 and AC7 were measured live (no test), AC8 is unmeasured. The live checks are recorded on #2375 and in `features.json`.
> - **Type checks and lint**: not re-run, because the archive changes only the spec folder. The work PRs (#2379, #2381) ran them in CI.
> - **No unrelated changes in the diff**: not asserted here; each work PR was reviewed on its own diff.

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [x] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command ✓ 2026-10-22 (nine entries; f5 partial, f8 blocked)
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [x] `verification.md` filled in ✓ 2026-10-22
- [x] PR opened referencing this spec folder ✓ 2026-10-17 (#2379 and #2381 name OPS-038)

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/OPS-038-gitea-forge-upgrade/features.json`):

```json
[
  {
    "id": "OPS-038-gitea-forge-upgrade-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
