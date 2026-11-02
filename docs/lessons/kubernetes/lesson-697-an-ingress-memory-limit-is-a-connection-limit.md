---
id: lesson-697-an-ingress-memory-limit-is-a-connection-limit
type: lesson
status: active
title: "An ingress memory limit is a connection limit"
created: "2026-11-02"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, traefik, load-test]
---

# An ingress memory limit is a connection limit

**Context**: Staging's load test OOMKilled Traefik at the 384 MiB it inherited from the `kube-system` LimitRange, so #2975 declared a limit of its own. The first figure, 768 MiB, came from an estimate of 120 KiB per connection.

**Problem**: 768 MiB was OOMKilled too, in 2 of 4 ramps at 3,200 VUs. The estimate had been divided from a run that kept far fewer connections open than the peak. Traefik's memory follows open connections, not request rate, and when a backend stalls the arrival-rate generator opens more, so memory climbs fastest at the moment the edge is already failing. At 1,536 MiB, four ramp pairs peaked at 973 MiB and none was OOMKilled, but Traefik still restarted twice at 1,600/s: exit 0, `failed liveness probe`, at 3.6 cores.

**Solution**: `k3s_traefik_memory_limit: 1536Mi` in the `k3s_server` role, measured by runs `f3f1ed1d`, `dbfa5158` and `4da6811b` under `docs/load-test/`. The liveness restart is #3018.

**Rule**: Size an edge's memory from the connections open at saturation, measured, never from healthy steps. A run that stops at its first degraded step has not seen the peak. And read `lastState.terminated` before calling a restart memory: `Completed` with exit 0 is the kubelet stopping the process, so more memory will not help.

**Tags**: `#traefik` `#load-test` `#issue-2975` `#issue-3018`
