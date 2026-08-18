---
id: lesson-247-k3s-server-can-deadlock-on-futex-after-bulk-d
type: lesson
status: active
created: "2026-05-10"
owner: manu
tags: [kubelab, lesson, k3s, kine, sqlite, gc, deadlock, futex, argocd, incident]
---

# K3s server can deadlock on futex after bulk-delete; restart releases the lock

**Context:** RELIAB-009 §9.3 deployment: applied `terminated-pod-gc-threshold=100` to aws1 (hub, t4g.small) which had accumulated ~1000+ zombie pods over 10 months. Goal was bulk-reaping the historical backlog. K3s restart triggered the new threshold; GC controller fired aggressively for ~3 minutes (5 events/sec) then stopped logging GC events at all. But `kubectl get pods -n argocd` continued timing out for 20+ minutes after GC silence.
**Problem:** Diagnostics showed: K3s server process in `WCHAN=futex_` state (kernel mutex wait) at 17% CPU and 69% RAM. kube-controller-manager logs had stopped emitting `delete pods` events. Node went `NotReady`. kubectl could fetch nodes (small response) and even Deployments/StatefulSets, but `kubectl get pods` (a larger response with thousands of tombstoned records) timed out at any timeout (8s, 20s, 60s). Auto-compaction of kine (SQLite-backed embedded etcd) appeared not to be running. The K3s server held an internal goroutine lock — likely in kine's slow SQL path — that blocked the pod list endpoint despite the GC having completed.
**Solution:** `sudo systemctl restart k3s` released the deadlock immediately. Post-restart: K3s up in ~30 seconds, kubectl responsive in 0.8s, memory recovered from 75MB to 460MB available (swap drained from 1.9GB to 65MB used). The kine SQLite data persists across restart, so no data loss. Operational rule: when K3s server is stuck post-bulk-delete (GC events silent, kubectl get pods timing out, process in futex state, memory thrashing), restart K3s is the right intervention — it's not a destructive operation, it costs 1-2 min API downtime, and frees kine-related goroutine locks that don't otherwise unwind. Do NOT add this to scheduled maintenance — only run on-demand when the symptom triggers.
**Tags:** `#k3s` `#kine` `#sqlite` `#gc` `#deadlock` `#futex` `#argocd` `#incident`
