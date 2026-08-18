---
id: lesson-200-cross-namespace-dns-fails-from-certain-pods
type: lesson
status: active
created: "2026-03-23"
owner: manu
tags: [kubelab, lesson]
---

# Cross-namespace DNS fails from certain pods

**Context**: Homepage pod trying to reach `traefik.kube-system.svc.cluster.local`.

**Problem**: Cross-namespace DNS resolution fails from the Homepage pod. The FQDN doesn't resolve despite the service existing.

**Solution**: Use ClusterIP directly (fragile — IP changes on service recreation). Better fix: create an ExternalName Service in the same namespace.

**Rule**: When a pod needs to reach a service in another namespace and FQDN fails, prefer ExternalName Services over hardcoded ClusterIPs. Hardcoded IPs are a ticking time bomb.
