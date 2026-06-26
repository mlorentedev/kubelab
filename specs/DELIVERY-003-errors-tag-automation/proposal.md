---
id: "DELIVERY-003-errors-tag-automation"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-06-26"
issue: "mlorentedev/kubelab#776"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, delivery, ci-cd, versioning, edge]
template_version: "1.0"
---

# DELIVERY-003-errors-tag-automation

> **Queued — sequenced AFTER [[DELIVERY-002-build-once-apps]]** (build-once api, kubelab#679). Amends [[adr-056-build-once-monorepo-apps|ADR-056]] (reverses its errors carve-out from *automation*, while keeping errors out of build-once / staging-sha). Form: **semver auto-pin, single SSOT** — professional + scalable, balanced with simplicity.

## Why

<!-- from issue #776: errors tag automation (semver auto-pin, single SSOT) -->

`errors` (edge service) is versioned by release-please, but its *deployed tag* is the one custom-app left off the automated promotion lane that `api`/`web` already ride (ADR-046). Today its version lives in **two places** — `edge.errors.version` (`common.yaml`, consumed by the VPS Ansible `errors_image`) **and** a hardcoded `newTag` in `infra/k8s/base/kustomization.yaml` (K3s) — and neither is on the automated path: `toolkit deployment promote` scopes to `apps.platform` (api, web) and rejects `edge.*`. So after a release-please `errors:X.Y.Z` bump, the K3s tag must be pinned **by hand** (the CLAUDE.md "custom app images need manual pin" gotcha). Risk: a forgotten pin silently leaves prod on a stale `errors` image. This closes that residual inconsistency.

## What

Right-sized automation (**not** full api-parity):

1. **Single SSOT** — `edge.errors.version` becomes the only source of the errors image tag. The hardcoded `kubelab-errors` `newTag` in `base/kustomization.yaml` is removed; K3s resolves the tag from the SSOT (generator-emitted or a toolkit-fed Kustomize image override), exactly as the VPS Ansible path already does.
2. **Auto-pin on release** — when release-please cuts `errors:X.Y.Z`, the deployed tag updates automatically for both runtimes (K3s + VPS), with no manual edit. `toolkit deployment promote` (or an equivalent first-class command) learns to write `edge.errors.version`, and the drift gate stays green (generated == committed).
3. **No staging-sha continuous lane, no build-once** — `errors` is static HTML on a pinned nginx base: low-risk, rarely-changing. Semver-everywhere is the right granularity; it does not need `api`'s per-commit sha lane or digest re-tagging (ADR-056 rationale stands for those).

## Out of scope

- **Full api-parity** for errors (per-env staging-sha continuous lane). Deliberately not — errors is edge infra; the ceremony isn't earned.
- **build-once / promote-by-digest** for errors (rebuild-on-release is fine; near-zero drift for static HTML — ADR-056).
- **Other edge services** (`dns-gateway`, `cloudflared`, `traefik`) — fold in later only if the same gap appears.

## Risks / open questions

- **[OPEN — implementation] How K3s reads the SSOT tag.** errors' K3s manifest is *static* (`base/edge/errors.yaml` + a base `images:` newTag), unlike api/web's *generated* deployments. Decide: extend the generator to emit errors' image from `edge.errors.version`, or have the toolkit write a Kustomize `images:` override. Prefer the path that keeps the drift gate (ADR-027) authoritative.
- **[OPEN — design] Prod gate vs auto-pin-everywhere.** Simplest = auto-pin to all envs on release (errors is low-risk; a bad error page is cosmetic, not a CrashLoop). Slightly more rigorous = auto-pin staging on release + add `errors` to the gated `promote-prod.yml` choices for prod. **Recommend the gated form** (keeps ADR-046's "prod is a deliberate gate" invariant) unless the simplicity win is judged decisive. Resolve when implementing.
- **[DEP] Sequenced after DELIVERY-002** — reuses the `deployment promote` plumbing that build-once touches; avoid a merge race by landing build-once first.

## Acceptance criteria

- [ ] `edge.errors.version` is the **single** SSOT for the errors image tag; no hardcoded `kubelab-errors` `newTag` remains in `base/kustomization.yaml`.
- [ ] On a release-please `errors:X.Y.Z`, the deployed K3s tag updates **without** a manual kustomization edit.
- [ ] VPS Ansible (`errors_image`) and K3s resolve the **same** SSOT version (no divergence possible).
- [ ] The config-drift gate stays green (generated == committed) after an errors promotion.
- [ ] `toolkit` refuses an errors tag that does not exist in the registry (same safety as `api`).

## References

- Bitácora: kubelab#776; parent epic kubelab#678 (ARGO-016 / ADR-046).
- ADR: amends `docs/adr/adr-056-build-once-monorepo-apps.md` (errors automation carve-out); refines `docs/adr/adr-046-gitops-delivery-promotion-strategy.md`.
- Sibling: [[DELIVERY-002-build-once-apps]] (build-once api — land first); DELIVERY-001 (#373, Argo Rollouts).
