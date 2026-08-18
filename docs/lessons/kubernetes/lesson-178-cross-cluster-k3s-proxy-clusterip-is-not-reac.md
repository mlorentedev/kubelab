---
id: lesson-178-cross-cluster-k3s-proxy-clusterip-is-not-reac
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# Cross-cluster K3s proxy: ClusterIP is NOT reachable from outside — use NodePort

**Context:** EndpointSlice pointing to aws1's Tailscale IP:80 returned 502. Argo CD ran as ClusterIP inside aws1's K3s — only accessible within that cluster, not on the host network.

**Solution:** Change argocd-server service to NodePort (30080). EndpointSlice targets 100.64.0.4:30080. Prod Traefik proxies to that.

**Rule:** When proxying K8s services cross-cluster via EndpointSlice, the target service MUST be NodePort or hostNetwork. ClusterIP is cluster-internal only. Document port in common.yaml SSOT.
**Tags:** `#k8s` `#traefik` `#endpointslice` `#nodeport` `#cross-cluster`
