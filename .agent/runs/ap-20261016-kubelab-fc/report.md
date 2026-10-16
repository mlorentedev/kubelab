# Autopilot run ap-20261016-kubelab-fc

**Verdict:** ended `queue-empty` after 4 items in about 3h20 (armed 08:00Z, closed about 11:20Z; the envelope ran to 18:00Z): 3 PRs merged, 2 PRs open for you, 0 parked. Question it answers: what is waiting on a human, and is anything irreversible? One thing is irreversible and already done (a billed Hetzner snapshot, below). Everything else waiting on you is reversible.

## Waiting on you, irreversible first

1. **Landed live, not undone by a revert:** `make vps-snapshot APPLY=1` took the prod VPS snapshot `kubelab-vps-2026-10-16` (Hetzner image 444208685, 7.28 GB, available). It is billed until deleted and nothing prunes it on its own (`KEEP=N` is opt-in). Delete it from the Hetzner console, or run `make vps-snapshot APPLY=1 KEEP=<n>` once it is no longer needed.
2. **PR #2337** (`chore/prod-vikunja-reconciler-token`): adds `apps.services.core.vikunja.reconciler_api_token` to `prod.enc.yaml`. SOPS file, so I did not merge it. Merging it unblocks `make sync-vikunja ENV=prod` (#1701 AC2/AC3) and #1699.
3. **PR #2343** (`fix/homepage-orphan-keys`): removes the three revoked Homepage credentials from `common.enc.yaml`; triaged, head `a45b2500`. SOPS file, so also yours.
4. **#2344** (opened by this run): staging's n8n Vikunja token has lost its tasks scope since #2327, which I merged after verifying the token only by bucket reads. Fix: mint a token on the `operator` account with Tasks, Projects (views, buckets) and task-comment groups, then `toolkit secrets set apps.services.automation.n8n.vikunja_api_token --env staging` and `make apply-secrets ENV=staging`; accept with `make n8n-probe ENV=staging`. Until then #2318's live move check cannot run. Merging #2349 changed no runtime: nothing is live until `make import-n8n` runs.

## Parked

None. Nothing is waiting on a question: each item either landed or waits on a merge or credential listed above.

## Done and merged

Merged by hand on the exact head SHA, after CI and a `## Review triage` comment, under the verbal 4-condition grant (the repo carries no `merge-grant.yml`).

- **#2349** (`Refs #2318`): an opened PR moves its Vikunja task to the Doing bucket (n8n workflow, `in_progress_bucket` in SSOT, ADR-066 amendment, lesson-579). #2318 stays open until the staging token is fixed and the move is seen live.
- **#2351** (`Closes #244`): `make vps-snapshot`, plan by default, idempotent per UTC day, labelled, verified `available`, opt-in label-scoped prune. Seven review rounds; every real finding was applied with a test written first (unfinished image on rerun, failed images not taking keep slots, retention warning, prune failure still reporting the taken snapshot, pagination, SSOT-driven fixtures). I dropped my own optional `SECRET_CATALOG` edit so the PR touched no secret-registry code. One red `Tests` was the known Kuma socketio flake (#1985/#1038), green on the next head.
- **#2353** (`Refs #1685`): every `infra/n8n/workflows/*.json` is imported or excluded with a reason; `sre-auto-triage.json` is excluded on purpose (no caller, no declared credential, `active: true`). The guard is derived from the directory and mutation-checked. #1685 stays open for AC3 (a second import changes nothing), which is not re-proven: staging's token is broken (#2344) and imports overwrite other lanes' staging n8n (TOOL-085).

## Housekeeping done

- #1699: the owning account is `operator`; the prod reconciler token is on #2337.
- #1701: left open on purpose. fix-tasks-vikunja-a0 listed what remains: prod AC2/AC3 needs #2337, AC7 as `manu`, AC9 SecretSpec waits on your expiry-class decision, spec closure.
- #2318: option B decision comment posted; no `blocked` label existed to drop.

## Skipped on purpose

#1365 (touches `infra/ansible` and Headscale, a live mesh mutation), #1395 (a three-way security-boundary decision the ticket leaves open), #1128 (became "track `poetry.lock`", a policy call), #1515 (secret-management code), #1908 and #1985 (Docker-dependent flake hunts), and the lanes peers hold (CLI-123, agent_stack, Vikunja reconciler).

## Evidence index

| Item | Command | Result |
|---|---|---|
| #244 | `make test` before the review rounds | 5390 passed, 18 skipped |
| #244 | `pytest tests/test_vps_snapshot.py`, CI `Tests` on `9e27885b` | 31 passed, CI green |
| #244 live | `make vps-snapshot`, `APPLY=1`, `APPLY=1` again | planned; created image 444208685, available; rerun said "already exists", no new image |
| #1685 | `make test` | 5395 passed, 18 skipped; guard red with a stray `zz-new.json`, removed afterwards |
| #2318 | `make test` | green after `make sync-platform-json`; live check NOT done (#2344) |
| merges | `gh pr view <n> --json state,mergeCommit` | #2349 `0b4366a3`, #2351 `54cd4d1c`, #2353 merged on `780b280c` |

## Budget spent

4 of 8 items; about 3h20 of the 10h window. No dollar figure exists: the provider exposes none here.

## Host-suspend line

`caffeinate -i` was held for the whole window and the session answered every poll without a gap. Inferred from uninterrupted polling, not measured by the OS.

## Disclosed lapses

- Merged #2327 earlier with the token verified only by bucket reads; it regressed staging (#2344).
- While adding a positive control to #2343 I ran a mutation on a dirty tree and restored it with `git checkout -- .`, which discarded the real edit. I noticed at once, redid it, and committed it (`a45b2500`). Nothing was lost, but the "commit before mutating" rule was not followed; `make mutate` was the right tool.

## The one next action

Merge #2337 and #2343 (both SOPS), then mint the staging n8n Vikunja token from #2344.
