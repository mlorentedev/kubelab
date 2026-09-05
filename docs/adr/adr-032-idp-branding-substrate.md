---
id: adr-032-idp-branding-substrate
type: adr
status: active
created: "2026-09-04"
owner: manu
---

# ADR-032: Centralized IDP Branding Substrate & Drift-Checked Theming Pipeline

## Status

Accepted — 2026-09-04

## Context

KubeLab operates an Internal Developer Platform (IDP) running multiple platform and observability services (Authelia, Homepage, Vikunja, Gitea, Grafana, Argo CD, Uptime Kuma, n8n). Historically, these services displayed discordant default appearances, generic login forms, and third-party upstream logos, creating visual fragmentation and diluting the professional presentation expected of an enterprise IDP.

Junior implementations typically approach branding through ad-hoc manual interventions:
- Modifying styles by hand across various service manifests.
- Forking upstream container images to replace assets, accumulating severe maintenance debt on version upgrades.
- Injecting client-side user styles via browser extensions.

To maintain KubeLab's high SRE and Platform Engineering standard, branding must be treated as **Infrastructure as Code (IaC)**: declarative, idempotent, version-controlled, zero-drift, and automated.

## Decision

1. **Single Source of Truth (SSOT):** Declare all design system tokens (palettes, typography, asset paths) exclusively in `infra/config/values/common.yaml` under the `branding:` key. No raw hexadecimal color codes or standalone brand assets are declared across disparate service manifests.
2. **Deterministic Projection & Drift Detection:** Implement `toolkit sync branding` (and integrate into `toolkit sync all`) to compile `common.yaml` tokens into the master stylesheet (`edge/errors/html/brand/brand.css`). CI enforces `--check` mode per ADR-027, failing on any undetected visual drift.
3. **Edge Asset Substrate via `edge/errors`:** Extend the existing hardened Nginx edge container (`edge/errors`) to serve `/brand/*` static assets with immutable caching (`Cache-Control: public, max-age=31536000, immutable`) and wildcard CORS headers. Re-use the existing automated multi-stage CI build, Trivy zero-vulnerability gate, and `release-please` promotion pipeline.
4. **Traefik Ingress Routing:** Expose `assets.staging.kubelab.live` and `assets.kubelab.live` directly to the edge static container, providing a unified CDN endpoint for all cluster services without creating new standalone workloads.
5. **Zero-Trust Identity Portal Experience:** Standardize Authelia as the unified authentication interface with branded assets, suppressing third-party raw login interfaces via OIDC auto-redirection across Grafana, Gitea, Vikunja, and MinIO.

## Consequences

### Positive
- **Maintainability:** Updating brand colors, typography, or logos requires modifying exactly one file (`common.yaml`) and running `toolkit sync branding`.
- **Zero Fork Debt:** All container images remain official upstream builds without local patches to maintain.
- **Reliability & Cache Busting:** Immutable cache headers ensure rapid client-side delivery while content-hashed ConfigMaps ensure deterministic rolling updates in Kubernetes.
- **SRE & Portfolio Value:** Demonstrates disciplined systems thinking, contract-driven generation, and production-grade Platform Engineering hygiene.
- **Security & Least Privilege:** Static brand assets are served with standard 0644 permissions inside a non-root container (UID 1001), eliminating privilege escalation vectors.
- **Verification & Test Coverage:** Comprehensive test harness in `tests/test_sync_branding.py` verifies deterministic CSS projection, fallback defaults, live synchronization, and fail-closed drift detection.

### Negative / Risks
- Ingress routing for `assets.*` depends on the `errors` deployment remaining healthy at the edge. (Mitigated by lightweight Nginx footprint: <32Mi RAM, 0.05 CPU).
