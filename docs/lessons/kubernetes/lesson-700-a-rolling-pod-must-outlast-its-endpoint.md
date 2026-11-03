---
id: lesson-700-a-rolling-pod-must-outlast-its-endpoint
type: lesson
status: active
title: "A rolling pod must outlast its endpoint, whichever app showed the loss"
created: "2026-11-03"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, traefik, rollout]
---

# A rolling pod must outlast its endpoint, whichever app showed the loss

**Context**: A 15-second smoke run of the load test at 50 requests/s happened to overlap a `web` deploy in staging. 7.16% of its requests failed (#2977).

**Problem**: When a pod is deleted, the kubelet sends SIGTERM while the endpoint controller removes it from the Service, and Traefik learns of the removal only at its next reload. A process that stops at once loses what Traefik routes to it in that gap. Measured at 50/s during a rollout landing inside the step: `web` lost 0.34% of 14,975 requests, maximum 5,001 ms. `api` lost nothing in the same test, so the loss depends on how the process stops, which is why one healthy app proves nothing about the others. Two of the first three attempts measured nothing: the rollout fell outside the step, and only the tool's `pod_replaced` field said so.

**Solution**: A native `lifecycle.preStop.sleep` of 5 seconds for every rolling workload behind an IngressRoute: the generated `api` and `web`, and the hand-written `errors`. The same run then lost 0 of 15,001, maximum 21 ms (`docs/load-test/2026-11-03-febb750e.md`). `tests/test_k8s_rollout_drains_before_stop.py` renders both overlays and fails on any such workload without it. `Recreate` Deployments are exempt: they have no second pod to drain to.

**Rule**: Apply a drain to the class, every rolling workload behind the router, not to the one app that showed the loss. And before trusting a rollout measurement, check that the pod was replaced inside the measured window.

**Tags**: `#rollout` `#traefik` `#issue-2977`
