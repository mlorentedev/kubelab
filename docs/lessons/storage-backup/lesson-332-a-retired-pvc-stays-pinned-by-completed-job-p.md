---
id: lesson-332-a-retired-pvc-stays-pinned-by-completed-job-p
type: lesson
status: active
created: "2026-08-15"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup]
---

# A retired PVC stays pinned by *completed* Job pods — and the CronJob's retention setting is what pins it

**Context:** ADR-061 moved Gitea off K3s and onto the Beelink, and the `gitea-data` PVC was duly removed from the manifests. Prod then sat permanently OutOfSync on exactly that one resource, for days, with Argo CD retrying the prune and never completing it.

**Problem:** the manifest was already correct — nothing in git referenced the PVC, and the desired state was unambiguous. The object was in `Terminating` with a `deletionTimestamp` set and simply would not go.

The blocker was the `kubernetes.io/pvc-protection` finalizer, which Kubernetes holds on a PVC while **any pod** still references it in its spec. "Any pod" includes pods in a terminal phase: three `pvc-backup-*` pods in `Succeeded`, from Jobs that predated the cutover, still carried the claim. They were not leftovers from a crash — `infra/k8s/overlays/prod/backup.yaml:27` sets `successfulJobsHistoryLimit: 3`, so the CronJob retains *up to* three successful Jobs, and their pods with them, for inspection. The retention knob that exists for debuggability and the thing holding the volume hostage are the same fact viewed from two sides. Nor does anything age them out: a per-Job TTL would have to be declared at `spec.jobTemplate.spec.ttlSecondsAfterFinished`, and that manifest does not configure one.

The second-order cost is the one that earned a ticket. An environment pinned at "1 of 91 OutOfSync, permanently" retrains you to read OutOfSync as background noise — so the next *genuine* drift arrives invisible. The drift detector was effectively down while looking green enough to ignore (kubelab#1072).

**Solution:** delete the three completed Jobs, which removes their pods. That drops the last references, the finalizer clears itself, and Argo CD completed the prune it had been retrying — prod went to 90/90 Synced.

Be precise about which step is the dangerous one. Deleting the Jobs is **not** destructive: it touches neither the PVC nor its contents. What it does is unblock the PVC deletion that was already pending, and whether the backing storage goes with it depends on the PV's reclaim policy. *That* is the step that warrants verifying a backup first and getting explicit authorization — here it destroyed the pre-cutover Gitea state, on the operator's explicit call.

**Rule:**
- **A PVC stuck in `Terminating` is almost never about the PVC.** Find what still references it, and search pods in *every* phase — `Succeeded` and `Failed` pods hold the finalizer exactly as firmly as `Running` ones.
- **Retiring a stateful service is not finished when its manifest is deleted.** Whatever referenced its volume outlives the service — backup Jobs above all, since their entire purpose is to touch the storage.
- **A retained Job is a live reference, not a record.** If Jobs mount PVCs, `successfulJobsHistoryLimit` is a storage-lifecycle setting, not just a debugging convenience; pair it with `spec.jobTemplate.spec.ttlSecondsAfterFinished` so retention is bounded by time as well as by count.
- **Treat a permanently OutOfSync environment as an outage of the drift detector**, not as a cosmetic annoyance to be filtered out mentally. One stuck resource is enough to hide every one that follows.

**Tags:** `#kubernetes` `#pvc` `#finalizer` `#argocd` `#cronjob` `#adr-061` `#gitea` `#gotcha`
