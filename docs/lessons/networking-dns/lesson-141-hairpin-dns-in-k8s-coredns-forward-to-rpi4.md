---
id: lesson-141-hairpin-dns-in-k8s-coredns-forward-to-rpi4
type: lesson
status: active
created: "2026-03-21"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Hairpin DNS in K8s: CoreDNS forward to RPi4

**Context:** OIDC token exchange failing in K3s — pods couldn't resolve `*.staging.kubelab.live` to reach Authelia.

**Problem:** K3s pods use internal CoreDNS (10.43.0.10) which only knows K8s service names. External domains like `auth.staging.kubelab.live` fail with "no such host". This breaks any pod-to-pod communication using external domain names (OIDC token exchange, webhooks, API calls).

**Options evaluated:**
1. CoreDNS `rewrite` to Traefik ClusterIP — rejected: hardcodes dynamic ClusterIP, complex regex with answer rewriting
2. Service mesh (Istio/Linkerd) — rejected: ~2GB RAM overhead, overkill for 12 services on single node
3. **CoreDNS `forward` to RPi4 (100.64.0.10)** — chosen: reuses existing DNS infra, zero hardcoding, one line per zone

**Solution:** K3s `coredns-custom` ConfigMap forwards staging zones to RPi4 CoreDNS. Applied via `make deploy-k8s` through the `cluster_bootstrap` layer (ADR-047/TOOL-009, 2026-06-17): the toolkit renders the `RESOLVE_RPI4_TAILSCALE_IP` placeholder via MagicDNS and server-side applies it outside the Kustomize overlay. (Previously a hand-rolled `dig|sed|kubectl` step in the now-removed `deploy-external` target.)

**Rule:** For K8s hairpin DNS, prefer forwarding to existing authoritative DNS over rewriting to ClusterIPs. ClusterIPs are dynamic; DNS infrastructure is stable. Service mesh only when >50 services or multi-cluster.
**Tags:** `#k8s` `#coredns` `#dns` `#oidc` `#hairpin` `#rpi4`
