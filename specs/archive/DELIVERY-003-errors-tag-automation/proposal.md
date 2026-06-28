---
id: "DELIVERY-003-errors-tag-automation"
type: spec
status: archived # draft | implementing | verifying | archived
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

- **[RESOLVED — implementation] How K3s reads the SSOT tag → extend `sync_k8s_images.py`.** `errors` is structurally a *semver-in-`common.yaml`* image (one `edge.errors.version`, shared across envs), exactly like the third-party images `sync_k8s_images.py` already syncs into `base/kustomization.yaml` — unlike api/web, whose tags live per-env in the overlays and ride `deployment promote`. So `errors` belongs on the **sync** lane, not the per-env promote lane: add it as a structured source (`{registry}/{edge.errors.image_name}:{edge.errors.version}`), emit it in the synced `images:` block, and delete the hand-edited `kubelab-errors` `newTag` from the custom-apps group. The drift gate (ADR-027) stays authoritative because the kustomization tag is now a pure function of `common.yaml`. (Rejected: extending the generator — it does not emit `kustomization.yaml` at all, NET-002.)
- **[RESOLVED — design] Prod gate vs auto-pin-everywhere → auto-pin everywhere via the single `common.yaml` SSOT, PR-mediated.** A *single* `edge.errors.version` cannot be gated per-env without splitting it into per-env overrides — which directly contradicts this spec's "single SSOT" goal (point 1). The gated form is therefore self-defeating here. Auto-pin is still **deliberate**: the bump lands as a PR a human merges (mirrors `staging-deploy.yml`), preserving ADR-046's "no unreviewed prod change" invariant without per-env divergence. `errors` is cosmetic-risk (a bad error page is not a CrashLoop), so the single shared version is the right granularity. (`errors` is NOT added to `promote-prod.yml` choices — those stay api/web per-env.)
- **[DONE — DEP] Sequenced after DELIVERY-002** — build-once landed first (#789); this reuses the `deployment promote` plumbing without a merge race.

## Acceptance criteria

- [x] `edge.errors.version` is the **single** SSOT for the errors image tag; no hardcoded `kubelab-errors` `newTag` remains in `base/kustomization.yaml`. ✓ `tests/test_sync_k8s_images.py`.
- [x] On a release-please `errors:X.Y.Z`, the deployed K3s tag updates **without** a manual kustomization edit. ✓ `release.yml` `promote-errors` + `_promote_errors`; `TestPromoteErrors::test_writes_edge_version_and_syncs`.
- [x] VPS Ansible (`errors_image`) and K3s resolve the **same** SSOT version (no divergence possible). ✓ both read `edge.errors.{image_name,version}`.
- [~] The config-drift gate stays green (generated == committed) after an errors promotion. ✓ stays green; gap noted in `verification.md` (gate doesn't independently assert kustomization==common.yaml — follow-up ticket).
- [x] `toolkit` refuses an errors tag that does not exist in the registry (same safety as `api`). ✓ `_promote_errors` `tag_exists`; `TestPromoteErrors::test_rejects_missing_tag` + smoke 404.

## References

- Bitácora: kubelab#776; parent epic kubelab#678 (ARGO-016 / ADR-046).
- ADR: amends `docs/adr/adr-056-build-once-monorepo-apps.md` (errors automation carve-out); refines `docs/adr/adr-046-gitops-delivery-promotion-strategy.md`.
- Sibling: [[DELIVERY-002-build-once-apps]] (build-once api — land first); DELIVERY-001 (#373, Argo Rollouts).
