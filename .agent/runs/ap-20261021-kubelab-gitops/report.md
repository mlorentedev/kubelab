# Run ap-20261021-kubelab-gitops

run ap-20261021-kubelab-gitops ended queue-empty after 4 items. 3 done, 1 parked, 2 merged, 1 left unmerged by design (PR1 draft).

## Waiting on you (irreversible first)

1. **#2594 (GITOPS-003 PR1) is a draft for the operator to merge.** It makes Argo CD post an `argocd/<app>` commit status per sync. Merging it before the token exists makes `make deploy-argocd` abort with FATAL. Order:
   1. Mint a fine-grained PAT: `mlorentedev/kubelab` only, Commit statuses read and write, expiry set.
   2. `toolkit secrets set argocd.github_status_token --env common --stdin`. The key name is new and can still be changed.
   3. Merge #2594, then run `make deploy-argocd`.
   4. Verify: `gh api repos/mlorentedev/kubelab/commits/<head>/statuses` shows `argocd/kubelab-staging`.
   5. Ping the DELIVERY-004 lane (`feat-delivery-004-mechanical-deploy-prs`): it gates on this.
   - Until step 2, prod `make secrets-audit` lists the key as missing. That is expected.
2. **#2580 (OPS-043) is parked and Blocked on the board** (see below).

## Parked

- **#2580 OPS-043.** The ticket's diagnosis is wrong: Jobs created by a CronJob do not count towards the Application's health. Staging is Degraded by the vikunja Deployment (#1783). Options:
  - **(A) Close it as misdiagnosed** (recommended).
  - **(B) Retarget it** to cleaning up failed Jobs with `ttlSecondsAfterFinished`, which is cosmetic only.

## Done

| PR | What | State |
|---|---|---|
| #2590 | `toolkit infra argo wait-status` (GITOPS-003 PR2a) | Merged `ed3b284e` |
| #2591 | `verify-product` exit 4 SUPERSEDED when a later merge pins another tag (closes #2584) | Merged `03c6b628` |
| #2594 | Argo CD commit statuses (GITOPS-003 PR1) | Draft, operator merge |

## Evidence index

| Check | Result |
|---|---|
| `make test` on #2591 | 6371 passed, exit 0 |
| `make test` on #2590 | One failure (GITOPS-003-f2 still listed as unwritten), fixed in `5c374d12` |
| `tests/test_argo_wait_status.py` | 21 passed |
| `tests/test_product_verify.py` | 48 passed |
| #2594 notification tests | 24 passed. The secrets, catalog and expiry suites add 449 passed. |
| #2594 template render (Go text/template + sprig v3.3.0) | Valid JSON, including a long message with quotes and multibyte characters, and an operation with no message and no syncResult |
| `make verify-product APP=web ENV=staging TIMEOUT=300` on `03c6b62` | VERIFIED. A 60 s attempt failed earlier only because Argo had not synced the merge yet, which is within the measured lag. |
| `make verify-product APP=web ENV=staging TIMEOUT=120` on `49638d3`, before the run | VERIFIED, exit 0 (posted on #2579 and #1478) |
| `make mutate` on every new guard | All red |

## Outside this run

- Hub rebuild: the token is not in Secret Manager, `infra/terraform/gcp` or cloud-init, so a recreated hub posts no statuses until it is. Unchecked task in `specs/GITOPS-003/tasks.md`.
- PR2b (`deploy-verify.yml`) touches `.github/**`, which is outside the envelope. It must treat exit 4 as neutral.

## Budget

- 4 items, one usage-limit pause (session limit, resumed after the reset), within the 6 h window.
- No dollar figure exists for this run.

## Host

`caffeinate -i -t 21600` was running from arming, so the window was covered.

## Worktrees

None removed.

- Removable: `feat-gitops-003-wait-status`, `fix-gitops-007-superseded`.
- Keep: `feat-feat-gitops-003-argo-status`. The doubled prefix comes from `dotf worktree add`; the branch is `feat/gitops-003-argo-status`.
- Keep: `chore-autopilot-run-20261021-gitops`, the run branch, never merged.

## Next action

Mint the PAT and follow the "Before merge" section of #2594.
