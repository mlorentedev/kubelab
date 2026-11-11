# Run report: forge console line (2026-11-11)

**Verdict:** queue-empty. Two PRs landed and one is landing; every remaining
item needs the owner (a release, a prod promotion, a `.github/` change, or a
decision).

## Waiting on you (irreversible first)

1. **Merge release #3275 (api 1.7.2)**, then `make promote-prod APP=api VERSION=1.7.2`
   and merge the promote PR. 1.7.2 re-tags `sha-59f1c41`, which contains #3246
   (Gitea next links) and #3265 (seed retry); `git diff 59f1c41 15cd1f0 -- apps/api`
   touches only `CHANGELOG.md` and `version.txt`. After the promotion, prod Loki
   should stop showing `next page points off` for `personal/resume` and
   `personal/imagesensortool`.
2. **Add a note to the api 1.7.1 release body:** it ships the 1.7.0 image
   (lesson-735). Editing a release was outside this run's authority.
3. **#3266**: the release guard (`.github/workflows/release.yml`, source
   equality of `apps/api` between pin and release). Frozen path; owner merges.
4. **#3267**: staging has no Gitea reader. A (staging reader + token) or B (drop
   Gitea sources from staging).
5. **#3264**: first Postgres connection refused at every api pod start; the
   kube-router NetworkPolicy timing hypothesis needs confirmation.
6. Older items still open on #2570: A8 usage counter (A/B), Gitea webhook,
   inbox reasons, AC6 alert, AC7 restore rehearsal, `apps/console` scaffold and
   the UX overhaul.

## Parked

None.

## Landed

- #3265: reconciler retries the wildcard seed from the store (closes #3247).
- #3269: lesson-735, a release re-tags whatever staging pins.
- #3282: lesson-735 guard corrected from an ancestor check to source equality
  (landing at report time).

## Evidence index

- #3246 pager fix: merged `171f651`, three mutations killed (`contract_test.go`).
- #3265: `TestReconcileSeedsAWildcardTheStartCouldNotSeed`,
  `TestReconcileDoesNotAskTheStoreOnceListed`; merge `59f1c41`.
- Staging pin: deploy PR #3277 merged, pin `sha-59f1c41`.
- #3264 staging repro: Loki 2026-11-11 08:19:49Z, comment on the issue.

## Budget

Window 07:40Z to ~08:45Z of the 12h envelope; ended early on queue-empty.
Host wake-lock: `caffeinate -i -t 43200` covered the window.

## Next action

Merge #3275, then promote api 1.7.2 to prod.
