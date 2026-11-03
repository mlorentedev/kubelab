---
id: lesson-701-a-liveness-probe-on-the-only-replica-must-outlast-saturation
type: lesson
status: active
title: "A liveness probe on the only replica must outlast saturation"
created: "2026-11-03"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, traefik, load-test]
---

# A liveness probe on the only replica must outlast saturation

**Context**: K3s ships Traefik as one replica with the chart's probes: `/ping` with a 2 s timeout, 3 failures 10 s apart. `/ping` is answered by the same process that carries the traffic.

**Problem**: At 1,600/s in staging (run `4da6811b`), Traefik was busy, not stuck: 3.6 cores, memory well under its limit. `/ping` took longer than 2 s, three times running, and the kubelet restarted it twice. With one replica, a restart drops every open connection and the edge serves nothing until it is back, so the probe turned a slow edge into a dead one, at the moment load was highest. The readiness probe had the same 2 s timeout, so one slow answer also took the only endpoint out of the Service.

**Solution**: #3018 made both probes declared values in the `k3s_server` role: liveness waits 5 s and restarts after 6 failures 15 s apart, about 90 s; readiness waits 5 s and needs 3 failures. Run `ed148e4a` repeated the ramps up to 2,000/s with 0 Traefik restarts. `tests/test_traefik_liveness_tolerates_saturation.py` holds the window between 60 and 180 s.

**Rule**: Liveness answers "is it stuck", never "is it slow". On a workload whose probe shares the serving path and that has no second replica, size the liveness window from saturation, measured, and keep it short enough to catch a real hang. Readiness can be stricter, but not so strict that one slow answer removes the only endpoint. Then expect what the restart was hiding: an edge that is no longer restarted keeps its connections, and its memory climbs further (#3057).

**Tags**: `#traefik` `#load-test` `#issue-3018` `#issue-3057`
