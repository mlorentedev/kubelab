---
id: lesson-003-burstable-qos-proved-the-wrong-container-had-
type: lesson
status: active
created: "2026-08-17"
owner: manu
tags: [kubelab, lesson]
---

# `Burstable` QoS proved the wrong container had a request (IDP-031)

**Context**: IDP-031's final phase had to show that `apprise` and `crowdsec` — the two pods whose **initContainers** declare no `resources` — come up with the `LimitRange` defaults applied. Both pods showed `qosClass: Burstable` in prod immediately after `selfHeal` landed the `LimitRange` and `ResourceQuota`. Burstable means "has requests, requests < limits", so the criterion looked met without touching anything.

**Problem**: It was met by the wrong container. Both pods' **main** containers carried explicit `resources` that pre-dated this spec entirely, and QoS class is computed over the whole pod — so `Burstable` was true before the `LimitRange` existed and would have stayed true if it never applied. Reading the object underneath showed `spec.initContainers[*].resources` was still `{}`. Neither pod had actually restarted since the manifests landed, and container resource attributes are fixed at *create* time: nothing about an existing pod changes when a `LimitRange` appears. An explicit `make restart-service` was needed before the initContainers picked up `128Mi/256Mi`.

The tell was available and ignored: a derived field that was already true for an unrelated reason cannot distinguish the state you are claiming from the state you had. `qosClass` is a summary over containers; the claim was about one specific container list.

**Solution**: assert on `spec.initContainers[*].resources` directly, and restart the workload first, because a `LimitRange` is an admission mutation and admission only runs on create. `tests/infra/test_k3s.py::TestNamespaceGovernance` reads the resource blocks, not the QoS class.

**Rule**: **A derived field is not evidence for a claim about its inputs.** QoS class, `Ready`, `Up`, an aggregate count — each summarises several things, so it can be true because of any one of them. When the claim names one specific input, read that input. And when the mechanism is admission-time — `LimitRange`, defaulting webhooks, injected sidecars — remember that existing objects are never revisited: an unrestarted pod is evidence about the past, not about the manifest you just applied. Same family as the drift gate whose green meant "nothing to compare" and the container limits that were declared but never in force (#1104, #1117).

**Tags**: `#kubernetes` `#limitrange` `#qos` `#admission` `#false-green` `#idp-031` `#proxy-signal`
