---
id: lesson-743-a-new-kind-reaches-argo-cd-only-after-register-spoke
type: lesson
status: active
created: "2026-11-12"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, rbac]
---

# A new kind in the overlays reaches Argo CD only after `register-spoke` runs in both envs, and merging the RBAC line does not do it

**Context**: OPS-065 (ADR-076) adds the first `ServersTransport` objects: one in the staging overlay, and one in prod that Headscale's IngressRoute references.

**Problem**: `tests/test_spoke_rbac_covers_manifests.py` failed until `serverstransports` was added to the write role in `infra/k8s/argocd/spoke-rbac.yaml`, and after the edit it passed. But that test reads git, not the cluster, and nothing applies `spoke-rbac.yaml` on merge: Argo CD does not manage its own spoke role. Live, `kubectl auth can-i create serverstransports.traefik.io -n kubelab --as=system:serviceaccount:kubelab:argocd-manager` answered `no` in both clusters with the line already merged (#3422). Had the manifest merged first, prod's sync would have failed on the `ServersTransport`, and an IngressRoute that names a transport Traefik cannot find is dropped, so `vpn.kubelab.live`, the bootstrap of every node, would have gone with it.

**Solution**: merge the RBAC line on its own, then `make register-spoke ENV=staging` and `make register-spoke ENV=prod` (each re-applies the role and re-creates the hub's cluster secret), confirm `can-i` answers `yes` in each cluster, and only then merge the manifest. Measured 2026-11-12: `clusterrole.rbac.authorization.k8s.io/argocd-manager-write configured`, then `yes`, in both.

**Rule**: a kind the spoke role does not already write is a three-step change, in this order: the RBAC line, `register-spoke` per env with a live `can-i`, then the manifest. The static guard proves the declaration, never the grant.

**Tags**: `#argocd` `#rbac` `#ops-065` `#pr-3422`
