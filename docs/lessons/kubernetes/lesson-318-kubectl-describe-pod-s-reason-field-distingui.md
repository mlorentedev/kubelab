---
id: lesson-318-kubectl-describe-pod-s-reason-field-distingui
type: lesson
status: active
created: "2026-08-12"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# `kubectl describe pod`'s "Reason" field distinguishes OOM from a probe-triggered kill — a bare exit 137 does not

**Context:** Verifying OPS-022 (#969) in staging, `import-n8n`'s `kubectl exec` failed mid-`deploy-k8s` with exit 137. First instinct: OOM — 137 is `128+SIGKILL`, and that's the textbook cgroup-OOM signature.

**Problem:** It wasn't OOM. `kubectl describe pod` showed `Last State: Terminated, Reason: Error` (not `OOMKilled`, which the kubelet reports verbatim when the cgroup OOM-killer fires) alongside a very specific event: `Liveness probe failed: ... context deadline exceeded` immediately followed by `Killing: Container n8n failed liveness probe, will be restarted`. The actual cause was CPU starvation, not memory: `kubectl top` showed 378m against a 200m request, which is not evidence of anything (requests don't throttle; only the limit does, and one sample can't show whether the limit was ever hit). The discriminating check was the container's own cgroup counters (`kubectl exec ... -- cat /sys/fs/cgroup/cpu.stat`): `nr_throttled=211/554` accounting periods (38%), with `throttled_usec` (30.9s) *exceeding* `usage_usec` (27.5s) — the container spent more wall-clock time waiting on its 1-core limit than it spent running. That, not memory pressure, is what made `/healthz` miss its 5s liveness timeout often enough to get killed.

**Solution:** Raised the CPU limit 1.0→2.0 cores (`infra/k8s/base/services/n8n.yaml`, PR #1022) and re-measured the same counter after a staging soak: throttled periods dropped 38%→3.3%, throttled/usage ratio dropped 112%→24%. The fix was verified by the same instrument that diagnosed the defect, not by "restarts stopped happening" (too slow a signal, and this session's soak window was too short to prove restarts alone).

**Rule:**
- **Exit 137 is SIGKILL — it says *who* ended the process, not *why*.** OOM-kill, a liveness-probe-triggered `Killing`, and a manual `kubectl delete --force` all produce it. `kubectl describe pod`'s `Last State.Reason` and the Events block distinguish them; the exit code alone does not.
- **CPU throttling needs its own evidence, not an inference from `kubectl top`.** A single usage sample can't show whether a *limit* was ever hit — only `cpu.stat`'s `nr_throttled`/`throttled_usec` can, and it was one `kubectl exec` away the whole time.
- **A tight liveness-probe timeout turns "slow" into "dead."** The mechanism connecting CPU throttling to a restart loop was the probe's 5s `timeoutSeconds` — under 38%-throttled periods, that budget just isn't enough, independent of whether the process was actually unhealthy.

**Tags:** `#kubernetes` `#cgroup` `#cpu-throttling` `#liveness-probe` `#n8n` `#ops-020` `#gotcha`
