---
id: lesson-305-a-limitrange-can-reject-pods-the-guardrail-ha
type: lesson
status: active
created: "2026-08-09"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# A LimitRange can *reject* pods — the guardrail has the same failure mode as the thing it guards (IDP-031)

**Context:** Implementing IDP-031 Phase 1 — landing a `LimitRange` on the `kubelab` namespace so that a `ResourceQuota` could safely follow. The spec's whole design rests on ordering: a quota rejects any pod omitting a dimension it constrains, and this namespace ships two initContainers that declare no resources at all (`apprise/seed-config`, `crowdsec/inject-whitelist`). So the LimitRange has to be live and proven before the quota exists.

**Problem:** The plan treated the LimitRange itself as risk-free — a pure floor that can only add. It is not. `default` is injected as a *limit* into every container that omits one, `defaultRequest` as a request, and the `request <= limit` invariant is validated *after* that injection. Two ways that bites:

- a container declaring `requests.memory: 512Mi` with no limit gets `limits.memory: 256Mi` injected — 512 > 256 — and is **rejected at admission**;
- a container declaring `limits.memory: 64Mi` with no request gets a 128Mi request injected, and is rejected the same way.

Neither is exotic: declaring a request without a limit is a common and otherwise valid manifest. The object introduced to stop the namespace exhausting the node could have made healthy pods inadmissible on their next restart — and it would have surfaced not at apply time but hours later, on the next unrelated rollout.

**Solution:** Measure before writing the manifest. One pass over both clusters intersecting *declares a request* with *declares no limit*, filtered to requests above the proposed default, plus the mirror case. Result: 0 in either category across both environments, 35 safe containers, only the 2 known unbounded initContainers — so the chosen 128Mi/256Mi were safe and the phase proceeded unchanged. Had the set been non-empty, the values or those manifests would have needed fixing first, and the spec would have been wrong about its own risk. The acceptance check then captured before/after across a real restart: both initContainers went `UNBOUNDED` → `128Mi`/`256Mi`.

The generic regression test uses `kubectl create --dry-run=server` rather than create-then-delete. A server-side dry run traverses the real admission chain — LimitRanger is a member of it — and returns the mutated object without persisting anything. That tests precisely the thing that can reject a pod, while keeping the infra suite read-only and therefore safe to run against prod.

**Rule:** Before adding an admission-time defaulter, enumerate the inputs it will *change*, not just the ones it will fill. A default that completes a partially-specified object can contradict what the object already declares, and admission validates the merged result, not your intent. State the check as "which existing objects would this reject?" — and if the answer is "none", have run the query that says so. The corollary for the test: assert against the admission chain, not against a sample of today's pods, or the check quietly stops covering anything the moment those pods are given explicit resources.

**Tags:** `#kubernetes` `#limitrange` `#resourcequota` `#admission` `#idp-031` `#preflight` `#dry-run-server` `#gotcha`

---
