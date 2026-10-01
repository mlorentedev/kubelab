---
id: "BACKUP-070-restore-window"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-01"
issue: "mlorentedev/kubelab#1998"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# BACKUP-070: Restore window

## Why

<!-- from issue #1998: BACKUP-070: a restore cannot take a prod app offline while Argo CD self-heals it -->

The restore runbook tells the operator to take a prod app's data offline before putting a restored copy in place. On prod that step does not hold: Argo CD prod runs `selfHeal: true` (ADR-037), Authelia and n8n declare `replicas: 1`, and a `kubectl scale --replicas=0` is reverted within one reconcile, so the pod comes back while its files are being replaced. The only way out today is a hand edit of the Application on the hub, which the standing orders forbid and the runbook cannot name. Without a codified window, every prod data restore (Postgres, Authelia, n8n) is either unsafe or manual.

## What

`make restore-window APP=<deployment> ENV=<staging|prod>` opens a window, and the same command with `END=1` closes it. Both go through the toolkit (`toolkit backup restore-window`), modelled on `argo-set-revision` (operator decision on #1998, 2026-10-01).

1. **Open.** The command pauses automated sync on the env's Application (`kubelab-<env>` on the hub) by setting `spec.syncPolicy.automated.enabled: false`. The patch carries the read's `resourceVersion` as a precondition, and it writes a holder annotation on the same object (`kubelab.live/restore-window`: Deployment, who and UTC start). It then scales the Deployment to zero on the spoke, waits until no pod of that Deployment exists and none mounts its claims, and prints the sync policy it replaced.
2. **Refuse a second window.** While the annotation is present, an open is refused and names the holder. There is no `FORCE`: `END=1` is the way out, and it prints what it closes.
3. **Close.** The command restores the sync policy **declared in git** (`infra/k8s/argocd/applications/<env>.yaml`, the same object `make deploy-apps` applies), never a value cached at open. It removes the annotation, prints the policy it replaced, and then **triggers a sync explicitly** (the `operation` patch `make sync-app` already uses). Re-enabling automated sync alone does not bring the replicas back: staging runs `selfHeal: false`, so a Deployment scaled to zero at an unchanged revision stays at zero (lesson-330). Finally it waits, bounded, for the Application to be Synced/Healthy and the Deployment to reach its declared replicas, and exits non-zero if either does not happen.
4. **Runbook.** The Postgres and Authelia/n8n sections of `docs/runbooks/offsite-backup-restore.md` call the window instead of "scale to zero".

## Out of scope

- A committed `ignoreDifferences` on replicas. The operator ruled it out: it would silence drift on every reconcile, not only during a restore.
- Pausing a single resource inside the Application. Argo CD has no per-resource auto-sync switch, so the window pauses the whole env's Application: a merge to master does not deploy to that env while a window is open. The holder annotation and `make check-apps` drift make that visible.
- Automating the restore itself (`pg_restore`, file copy). The window only makes the existing manual steps safe.

## Risks / open questions

- **A window left open.** Prod would stop receiving merges until someone closes it. Mitigation: the annotation records who and when, `END=1` is idempotent (closing an already-closed window reports it and exits 0), and the runbook states the close as a mandatory step. An alert on an open window older than N hours is a follow-up, not this spec.
- **`automated.enabled` support on the hub's Argo CD (v3.4.1).** Upstream documents the field (`SyncPolicyAutomated.Enabled`). Implementation verifies it on the live CRD (`kubectl explain application.spec.syncPolicy.automated.enabled` against the hub) before relying on it. If it is absent, the fallback is removing `automated` and restoring it from git at close, which the "restore from git" design already supports.
- **`deploy-apps` during a window** re-applies the git manifest and silently ends the pause. The window command cannot prevent that. `make deploy-apps` refuses while a holder annotation is present (part of this spec, AC5).
- **Impersonation.** Patching the Application uses the hub kubeconfig, and scaling uses the spoke's (`argocd-manager` is the GitOps writer; a scale by the operator is an operator action). No RBAC change is expected. Verify on staging.

## Acceptance criteria

- [ ] **AC1** Opening a window on staging (`make restore-window APP=n8n ENV=staging`) leaves `kubelab-staging` with `automated.enabled: false` and a holder annotation, `deploy/n8n` at zero pods, and prints the replaced sync policy. Verified live by reading the Application and the Deployment back.
- [ ] **AC2** A second open while the window is held exits non-zero and names the holder. Unit test, plus once live on staging.
- [ ] **AC3** `END=1` restores the sync policy declared in `infra/k8s/argocd/applications/<env>.yaml`, removes the annotation, prints what it replaced, triggers an explicit sync, and exits 0 only once the Application is Synced/Healthy and the Deployment is back to its declared replicas. A unit test asserts the restored policy equals the git manifest's, and the staging run proves the rest. Closing with no window open exits 0 and says so.
- [ ] **AC4** Every patch carries the read's `resourceVersion`, so a concurrent writer turns the patch into a conflict instead of being overwritten. Unit test on the built argv, same shape as `set_revision`'s.
- [ ] **AC5** `make deploy-apps` refuses while any Application carries the holder annotation and names it. Unit test.
- [ ] **AC6** `docs/runbooks/offsite-backup-restore.md` uses the window in the Postgres and Authelia/n8n sections, opening before the data is replaced and closing after it. No section still says "scale to zero".

## References

- Bitácora: #1998 (operator decision in the issue, 2026-10-01). Parent #1923. Found by BACKUP-068 (#1996).
- ADR-037 (selfHeal per environment), ADR-046.
- `toolkit/features/argo_manager.py` (`set_revision`: holder semantics, resourceVersion precondition), lesson-475 (one shared slot, refuse a second holder).
