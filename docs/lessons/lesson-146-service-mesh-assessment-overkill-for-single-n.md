---
id: lesson-146-service-mesh-assessment-overkill-for-single-n
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, architecture, service-mesh, k3s, assessment]
---

# Service mesh assessment: overkill for single-node K3s

**Context:** Evaluating Istio/Linkerd for mTLS and traffic observability on K3s cluster.

**Problem:** Single-node K3s with 12 services. Service mesh adds ~2GB RAM overhead (sidecar per pod), operational complexity (CRDs, certificate rotation, upgrade path), and debugging difficulty (envoy proxy chain).

**Solution:** Defer service mesh. Current needs (hairpin DNS, basic auth) solved with CoreDNS rewrite + Authelia. Reconsider in Phase 4 (mTLS requirement), Phase 6 (traffic observability), or when multi-cluster.

**Rule:** Service mesh justified when: >50 services, multi-cluster, strict mTLS compliance, or traffic shaping needs. For <20 services on single node, simpler tools (CoreDNS, middleware, NetworkPolicies) suffice.
**Tags:** `#architecture` `#service-mesh` `#k3s` `#assessment`
