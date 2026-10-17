---
id: lesson-317-kubectl-exec-with-a-cli-that-boots-a-full-run
type: lesson
status: active
created: "2026-08-12"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# `kubectl exec` with a CLI that boots a full runtime shares the pod's own cgroup

**Context:** Gathering per-instance emptiness evidence for ADR028-004 (#988) meant counting n8n's staging workflows. The obvious tool existed already — n8n ships `n8n list:workflow` — so the natural move was `kubectl exec <pod> -- n8n list:workflow`.

**Problem:** The command hung past its own timeout, was killed with exit 137, and the pod failed its liveness probe and restarted seconds later — an active incident triggered by a read-only diagnostic. The n8n CLI doesn't just query the running server; it boots a second, full copy of the n8n runtime inside the container to do it. That process runs in the *same* cgroup as the server process already serving traffic, competing for the same CPU and memory ceiling. Against a pod with no headroom to spare — this one turned out to already be CPU-throttled under its 1-core limit, filed separately as #1009 — the exec was enough to tip it over. The evidence pod was gone (replaced by an unrelated rollout restart from a parallel session) before its `Last State: Terminated` reason could even be read, so the exact kill mechanism is unconfirmable after the fact.

**Solution:** Never got the workflow count from inside the pod. Used `kubectl cp` to copy the SQLite files (`database.sqlite` + `-wal` + `-shm` — the WAL held 2.7MB of uncheckpointed writes, so all three were needed for a correct count) to local disk and queried them with Python's `sqlite3` module. Bytes-out costs the container nothing; it never touches the running process's cgroup.

**Rule:**
- **`kubectl exec` runs inside the target container's own resource limits, not a scratch space of its own.** A CLI that starts a second app-runtime process (this one; `gitea admin <cmd>` would hit the identical shape) is not a lightweight query — it's launching a second workload inside a box already sized for one.
- **Prefer copying data out over executing anything inside a live, resource-constrained pod.** `kubectl cp` + local tooling is strictly safer for read-only inspection: zero contention with what's already running. This repo already has the correct pattern committed — the backup CronJob (`overlays/prod/backup.yaml`) runs its own `sqlite3` against the same class of PVC in a **separate pod**, with its own limits, never via exec into the live service.
- **A container's official CLI is not automatically a safe diagnostic tool.** It was built to be run once, by an operator, with the resources to spare — not assumed to be free against a pod already near its ceiling.

**Tags:** `#kubectl` `#kubectl-exec` `#cgroup` `#n8n` `#resource-limits` `#diagnostics` `#adr028-004` `#gotcha`
