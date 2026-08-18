---
id: lesson-181-argo-cd-spoke-registration-scoped-rbac-cluste
type: lesson
status: active
created: "2026-03-23"
owner: manu
tags: [kubelab, lesson]
---

# Argo CD spoke registration: scoped RBAC > cluster-admin

**Context**: Registering spoke clusters in Argo CD hub (ADR-023 Phase 3, ARGO-002).

**Problem**: `argocd cluster add` CLI creates a ServiceAccount with `cluster-admin` ClusterRoleBinding. If hub is compromised, attacker gets full admin on all spokes — unacceptable blast radius.

**Solution**: Declarative two-role RBAC pattern:
- `ClusterRole + ClusterRoleBinding` for cluster-scoped reads (namespaces, nodes, CRDs, events)
- `ClusterRole + RoleBinding` (in `kubelab` namespace) for workload CRUD

This limits Argo CD to managing only the `kubelab` namespace. No access to kube-system, no privilege escalation, no cluster-admin.

**Rule**: Never use `argocd cluster add` in production. Always define explicit scoped RBAC. Use two-role pattern: ClusterRoleBinding for cluster reads, RoleBinding for namespaced writes. SA lives in the managed namespace (not kube-system).
