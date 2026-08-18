---
id: lesson-248-activating-aggressive-gc-threshold-on-a-backl
type: lesson
status: active
created: "2026-05-10"
owner: manu
tags: [kubelab, lesson, k3s, gc, etcd, kine, backlog, ordering, runbook, disk-pressure]
---

# Activating aggressive GC threshold on a backlog cluster needs manual pre-cleanup

**Context:** RELIAB-009 §9.3 lowered `terminated-pod-gc-threshold` from K3s default 12500 to 100 on aws1 hub. The hub had ~1000 historical zombie pods (Completed/ContainerStatusUnknown/Error) accumulated since the 2026-05-06 OOM cascade. The expectation was: K3s restart with new threshold → kube-controller-manager auto-reaps backlog gradually → cluster settles.
**Problem:** Reality was: the bulk GC pass generated ~5 delete events/sec for ~3 minutes, which (a) blew out journald+apt logs pushing disk from 76% to 91% (kubelet disk-pressure threshold is 85% → NotReady), (b) saturated K3s server CPU at load 3.0 on a 2-vCPU instance, (c) eventually deadlocked K3s on a kine SQLite goroutine lock (separate lesson), and (d) bloated kine state.db from 168MB to 200MB (tombstones not yet compacted). Net effect: hub was effectively offline for 20+ minutes. The original RELIAB-009 plan called out "Immediate cleanup (one-shot, not part of the PR)" — but it was framed as cosmetic, not as a hard prerequisite.
**Solution:** When tightening GC threshold on a cluster with significant pod backlog, the order matters: (1) Manual chunked cleanup first — `kubectl delete pods -A --field-selector=status.phase=Succeeded` in batches (e.g. namespace by namespace, with brief waits between to let kine breathe), (2) THEN apply the new threshold via Ansible/Helm. The new threshold should never have to do the initial mass purge — it should only handle the trickle of post-cleanup zombies. Defense-in-depth: provision `make maintain NODE=<hub>` before the threshold change so disk has headroom for the unavoidable log spike, even with chunked cleanup. Document this as a runbook: "tightening etcd/GC thresholds on backlogged clusters" → vault 40-runbooks/. Also: keep `k3s_etcd_snapshot_retention: 2` on small-disk hubs to minimize baseline disk usage so a log spike doesn't trip pressure threshold.
**Tags:** `#k3s` `#gc` `#etcd` `#kine` `#backlog` `#ordering` `#runbook` `#disk-pressure`
