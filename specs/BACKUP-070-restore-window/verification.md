---
tags: [spec, verification, templates]
created: "2026-10-01"
---

# Verification - BACKUP-070-restore-window

## Evidence

Live runs on staging used `ea6b474c`, the branch HEAD. Kubeconfigs were `~/.kube/kubelab-hub-config` for the hub and `~/.kube/kubelab-staging-config` for the spoke. The setup check passed: `kubectl explain application.spec.syncPolicy.automated.enabled` on the hub names the field (Argo CD v3.4.1).

- [x] **AC1.** Run 3, 2026-10-01T21:56:11Z to 21:57:02Z, reads the result back:
  - the Application has `automated.enabled=false` and the annotation `{"by": "manu@msi", "deployment": "n8n", "since": "2026-10-01T21:56:12Z"}`;
  - `deploy/n8n` reads `spec=0 ready=` (empty);
  - the open printed the replaced policy `{'automated': {'prune': True, 'selfHeal': False}, ...}`.

  The open returns only once no pod matches the selector and none mounts the claims (`test_the_open_returns_only_once_no_pod_mounts_the_claims`, `test_a_pod_from_another_owner_mounting_the_claim_still_blocks`). Commits `230005a6`, `0b635a12`.
- [x] **AC2.** Run 2, 2026-10-01T21:52:03Z to 21:53:35Z, exit code 0 overall. The second open exited 1 with "kubelab-staging already has a restore window open: deployment 'n8n', held by manu@msi since 2026-10-01T21:52:05Z". Unit test: `test_a_second_open_names_the_holder_and_patches_nothing`.
- [x] **AC3.** Run 3, after `END=1`:
  - `enabled=[]`, `sync=Synced`, `health=Healthy`, `ann=[]`;
  - `deploy/n8n` reads `spec=1 ready=1`;
  - the close printed the policy it replaced;
  - a second `END=1` printed "no window open on kubelab-staging; nothing to close" and exited 0.

  Unit tests: `test_the_restored_policy_is_exactly_gits[staging|prod]`, `test_declared_sync_policy_reads_the_manifest_deploy_apps_applies`, `test_the_close_triggers_one_sync_at_the_applications_revision`, `test_a_sync_that_never_restores_the_replicas_fails_with_what_it_saw`, `test_an_unhealthy_application_fails_the_close` and `test_closing_with_no_window_open_is_a_no_op`. Commits `230005a6`, `ea6b474c`.
- [x] **AC4.** Unit tests:
  - `test_one_merge_patch_pauses_sync_and_names_the_holder_under_the_reads_resource_version`
  - `test_the_close_patch_carries_the_reads_resource_version`
  - `test_a_conflict_is_retried_once_on_a_fresh_read`
  - `test_two_conflicts_in_a_row_fail_and_scale_nothing`

  Commit `230005a6`.
- [x] **AC5.** Unit tests, commit `0b635a12`:
  - `TestCheckWindow` exits 0 with no window, 1 naming the holder, and 2 with CANNOT CHECK when the hub cannot be read;
  - `test_deploy_apps_checks_the_window_before_it_applies` asserts that `check-window` runs before `kubectl apply` in the `deploy-apps` recipe.
- [x] **AC6.** The `features.json` f4 command exits 0 on `642955c1`: no "scale --replicas=0", "scaled to zero" or "#1998 is the fix" remains, and the runbook has 5 `make restore-window` mentions. The Postgres section and the Authelia/n8n section each open the window before replacing data and close it afterwards.

## Test status

- Test suite: `make test` on this branch: 3425 passed, 16 skipped, 1 failed. The failure was `test_the_table_covers_every_site`: the new `restore-window` target was missing from `ENV_TARGETS`. It is now added with its `prod` default, and that file passes 81/81.
- `poetry run pytest -q -p no:cacheprovider --no-cov tests/test_restore_window.py`: 27 passed.
- Mutation proofs. Each mutation was committed first and restored with `git checkout HEAD --`, and each turned the named tests red:
  - M1: the close stops sending `null` for keys that git does not declare. Red: `test_the_restored_policy_is_exactly_gits`.
  - M2: `_blocking_pods` ignores the claims. Red: `test_a_pod_from_another_owner_mounting_the_claim_still_blocks`.
  - M3: no sync operation. Red: `test_the_close_triggers_one_sync_at_the_applications_revision`.
  - M4: the no-clobber guard is removed. Red: `test_a_sync_argo_cd_already_started_is_not_overwritten` and `test_a_running_operation_is_not_overwritten_either`.
- Manual smoke test: three live runs on staging, logs kept in the session scratchpad.
  - Run 1 at 21:49:55Z.
  - Run 2 at 21:52:03Z, the f3 command verbatim.
  - Run 3 at 21:56:11Z, with Deployment readback.
  - After each run: Synced/Healthy and n8n at 1/1. `toolkit infra argo check-drift` reported "No drift — live Applications match git", and `toolkit infra argo check-window` reported "No restore window is open" (both rc 0, re-run after run 3).
- No regressions in the existing test suite: yes.

## Decisions made during implementation

- **The close does not overwrite a sync that Argo CD already started.** Run 1's sync history showed that re-enabling `automated` started a sync on its own, `{'automated': True}` at `eba28e55`, because git had moved since the last sync. An explicit `operation` written after it would replace that sync, or a Running one. The close now sends a sync only when the read it patches under shows no `operation` and no Running phase. Run 3 recorded `initiatedBy {"automated":true,"username":"restore-window"}`, meaning Argo CD folded the two into one operation. Recorded in lesson-501.
- **The wait for pods also checks claim mounts, not only the selector.** A pod from another owner that mounts the same PVC (a debug pod, a Job) would still write to the data being replaced.
- **The open refuses an Application without `automated`.** There is nothing to pause there, and a close would "restore" a policy that was never paused.
- **Pausing at the hub (scaling the application-controller) was rejected.** It stops every Application on the hub, prod included, to restore one app (proposal, Out of scope).

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/gitops-delivery/lesson-501-re-enabling-argo-cd-auto-sync-starts-a-sync-an-explicit-one-can-overwrite.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: this applies ADR-037's per-env sync policy and decides nothing new about it
- [x] New pattern candidate for `00_meta/patterns/`? no: Argo CD specific and seen in one project

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-070-restore-window/` -> `specs/archive/BACKUP-070-restore-window/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
