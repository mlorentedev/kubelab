---
id: "TOOL-036-platform-manifest-sync"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-09-05"
issue: "mlorentedev/kubelab#1347"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, ssot, sync, platform, idp]
template_version: "1.0"
---

# TOOL-036: Export public platform services and topology manifest from common.yaml

## Why

KubeLab's `common.yaml` is the Single Source of Truth (SSOT) for all clusters, nodes, and platform services. The public `/lab` and `/lab/idp` interfaces on `mlorente.dev` (`web` repository) consume `platform.json` to present the hybrid cloud/edge architecture, service registry, node specs, and architecture diagrams. However, `platform.json` currently has no automated producer in `kubelab`, leaving it manually maintained, prone to silent drift, and creating risk of accidental exposure of internal endpoints or addressing (tracked in `kubelab#1347` and `web#162`).

## What

Provide `tk sync platform-json` (and `make sync-platform-json` / `make sync-platform-json-check`) in `toolkit/` to project `infra/config/values/common.yaml` into the sanitized public schema of `platform.json`:
- **Sanitization & Zero-Addressing (ADR-056 §3)**: Omit all private addressing (LAN IPs `172.16.1.x`, `10.0.0.x`, Tailscale CGNAT IPs `100.64.0.x`, public VPS IP `162.55.57.175`, and `.internal` MagicDNS domains). Omit `url` and `healthEndpoint` for non-public services.
- **Fleet & Cluster Summary**: Compute `activeNodes`, `totalServices`, `kubernetesClusters`, and `kubernetesNodes` directly from `common.yaml`.
- **Node Topology**: Project the 9 fleet nodes (`vps`, `gcp1`, `ace1`, `ace2`, `jetson`, `beelink`, `rpi4`, `rpi3`, `aws1`) with hardware specifications, runtime (`k3s`, `docker`, `systemd`, `standby`), roles, and environments.
- **Services Catalog**: Project platform services across categories (`AI & Inference`, `Core Gateway`, `GitOps & Delivery`, `Observability`, `Storage & Data`), tech stacks, and access boundaries (`public` vs `mesh`/`auth`).
- **Architecture Diagrams**: Export Mermaid diagram specifications (`topology`, `gitops`, `security`, `ai-mcp`, `dns`) aligned with the SSOT.
- **Provenance & Drift Detection**: Populate `generated_at` (ISO 8601) and `source_commit` (`git rev-parse HEAD`), with `--check` returning exit 1 on drift.

## Out of scope

- Modifying Astro components in `web` (handled in downstream `web` PRs).
- Live client-side reachability probing (already implemented in `web`).
- Retiring `homepage.yaml` (executed in a subsequent PR after `web` ingests the generated artifact).

## Risks / open questions

- **Downstream compatibility with `web`:** The schema must match `site/src/data/platform.ts` in `Projects/web` without breaking existing type assertions or tests (`lab-sections.test.mjs`, `lab-idp-data.test.mjs`).
  - *Resolution:* Pin field names and enum values (`healthy`, `warning`, `offline`, `standby`, `k3s`, `docker`, `systemd`) to match `platform.ts` exactly.
- **Information leakage:** A bug in filtering could leak internal IPs or private dashboard URLs into public JSON.
  - *Resolution:* Automated negative assertions in `test_sync_platform_json.py` scanning the output JSON for any RFC1918, CGNAT, or raw IP patterns.

## Acceptance criteria

- [ ] `tk sync platform-json` outputs valid `platform.json` conforming to `site/src/data/platform.ts` schema from `common.yaml`.
- [ ] Output strictly enforces Zero-Addressing (ADR-056 §3): zero IP addresses, zero `.internal` hostnames, and zero private service URLs.
- [ ] Drift check `tk sync platform-json --check` exits 0 when committed matches generated output, and exits 1 with diff when drifted.
- [ ] Makefile targets `make sync-platform-json` and `make sync-platform-json-check` wired and passing.
- [ ] 100% unit test coverage with negative controls against credential and address leakage.

## References

- GitHub issue: `mlorentedev/kubelab#1347` (Work-gate)
- Downstream issue: `mlorentedev/web#162` (WEB-073)
- Related ADR: `docs/adr/adr-032-idp-branding-substrate.md` (`kubelab`)
- Related ADR: `Projects/web/docs/adr/ADR-056-live-platform-cockpit-architecture.md` (`web`)
