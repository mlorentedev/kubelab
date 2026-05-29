---
id: "kubelab-adr-003-hybrid-rpi-hetzner"
type: adr
status: accepted
tags: [adr, kubelab]
created: "2026-02-08"
owner: manu
---

# ADR-003: Hybrid infrastructure with Raspberry Pi and Hetzner VPS

**Status**: Accepted

**Date**: 2024-01-01

## Context

KubeLab needed infrastructure for 40+ services with varying requirements:

- Some services need public internet access with low latency (blog, APIs, public tools)
- Some services are internal-only (monitoring dashboards, automation, home network tools)
- Budget constraints: dedicated cloud hosting for 40+ services would cost €200-400/month
- Learning goal: hands-on experience with hybrid infrastructure for CV target positioning

Hardware available: 2-3 Raspberry Pi nodes (ARM64, 4-8GB RAM) at home, plus budget for one cloud VPS.

## Decision

Adopt a hybrid architecture:

- **Hetzner VPS** (AMD64): public-facing services, Traefik entrypoint, DNS management
- **Raspberry Pi cluster** (ARM64): internal services, monitoring, automation, storage-heavy workloads

Connected via WireGuard VPN tunnel for secure cross-node communication.

## Consequences

**Positive**:

- Monthly cost ~€10-15 (Hetzner CX21) vs €200+ for full cloud hosting
- Real-world hybrid infrastructure experience directly applicable to enterprise environments
- Physical hardware ownership: no vendor lock-in for internal services
- Portfolio showcase: demonstrates multi-arch, multi-cloud architecture skills

**Negative**:

- Home network dependency: ISP outages affect internal services
- Multi-arch builds required for every container image (amd64 + arm64)
- Latency between nodes (home ↔ Hetzner) adds complexity for stateful workloads
- Single point of failure: home power/network

**Neutral**:

- WireGuard overhead is negligible (~3-5% throughput reduction)
- Forces good practices: health checks, graceful degradation, workload placement decisions

## References

- Runbooks — Deployment and networking procedures
-  — Raspberry Pi specifications and setup
