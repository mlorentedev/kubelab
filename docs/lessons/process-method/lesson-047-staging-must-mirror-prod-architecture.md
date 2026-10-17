---
id: lesson-047-staging-must-mirror-prod-architecture
type: lesson
status: active
created: "2026-02-09"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Staging Must Mirror Prod Architecture

**Context**: Designing a staging environment on homelab with Raspberry Pis.

**Problem**: If prod is a single-VPS with Docker Compose, staging must be single-node with Docker Compose. Using RPis as stack nodes introduces architectural differences that invalidate staging→prod validation.

**Solution**: MiniPC B = staging (VPS mirror). RPis = cross-cutting infrastructure (VPN, DNS, external monitoring), NOT stack nodes.

**Rule**: staging == prod in architecture. Auxiliary infra (VPN, DNS, monitoring) lives on separate nodes to avoid contaminating validation.
