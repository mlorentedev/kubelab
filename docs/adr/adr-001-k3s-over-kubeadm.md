---
id: "kubelab-adr-001-k3s-over-kubeadm"
type: adr
status: accepted
tags: [adr, kubelab]
created: "2026-02-08"
owner: manu
---

# ADR-001: k3s over kubeadm for Kubernetes distribution

**Status**: Accepted

**Date**: 2024-01-01

## Context

KubeLab runs on a hybrid infrastructure combining 2-3 Raspberry Pi nodes (ARM64, 4-8GB RAM) with a Hetzner VPS (AMD64). We needed a Kubernetes distribution that could:

1. Run on resource-constrained ARM hardware (RPi has 4-8GB RAM total)
2. Support multi-architecture clusters (arm64 + amd64)
3. Be simple enough for a single operator to maintain
4. Provide production-grade features without enterprise complexity

Alternatives considered: kubeadm, minikube, microk8s, kind.

## Decision

Use k3s as the Kubernetes distribution for all KubeLab nodes.

## Consequences

**Positive**:

- Memory footprint ~512MB vs ~2GB for kubeadm — critical for RPi nodes where every MB counts
- Single binary, no external dependencies (embedded etcd via SQLite/dqlite)
- Built-in Traefik ingress, CoreDNS, local-path-provisioner — zero additional setup
- Multi-arch support works out of the box
- Simpler upgrades: single binary replacement vs coordinated component upgrades

**Negative**:

- Some CKA exam topics (kubeadm bootstrap, etcd backup/restore) require separate study environments
- Less control over individual component versions (bundled)
- Community smaller than kubeadm, though growing rapidly

**Neutral**:

- kubectl, manifests, and Helm charts are 100% compatible — skills transfer directly to full k8s
- CNCF certified distribution, so CKA/CKAD knowledge applies

## References

- https://k3s.io
- Certification roadmap — CKA/CKAD certification targets
