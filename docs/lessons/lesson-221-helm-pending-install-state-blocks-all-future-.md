---
id: lesson-221-helm-pending-install-state-blocks-all-future-
type: lesson
status: active
created: "2026-03-27"
owner: manu
tags: [kubelab, lesson, helm, argocd, debugging, aws]
---

# Helm pending-install state blocks all future upgrades

**Context:** Argo CD initial Helm install on t4g.micro timed out (OOM). All subsequent helm upgrade commands failed with "another operation in progress".
**Problem:** Helm revision 1 stuck in `pending-install` status. Helm refuses any operation when a release is in a transient state. Pods were actually running fine (K8s reconciled independently of Helm), but Helm's state was stuck.
**Solution:** `helm rollback argocd 1 -n argocd` — rollback to the pending revision marks it as deployed, unblocking future upgrades. Then re-run `helm upgrade` normally. This is safe because Helm rollback re-applies the same manifest.
**Tags:** `#helm` `#argocd` `#debugging` `#aws`
