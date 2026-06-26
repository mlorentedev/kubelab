---
id: "adr-056-build-once-monorepo-apps"
type: adr
status: accepted
created: "2026-06-26"
tags: [architecture, gitops, ci-cd, versioning, environment-promotion, supply-chain, delivery]
related:
  - adr-055-semver-everywhere-delivery
  - adr-046-gitops-delivery-promotion-strategy
  - adr-053-platform-product-repos
  - adr-027-config-drift-gate
issue: "mlorentedev/kubelab#679"   # ARGO artifact-parity
---

# ADR-056: Build-once / promote-by-digest for the api image (monorepo)

## Status

Accepted — 2026-06-26

Extends [ADR-055](ADR-055-semver-everywhere-delivery.md) (accepted for the extracted `web` repo) to kubelab's `api` image. Refines [ADR-046](adr-046-gitops-delivery-promotion-strategy.md) D2 by closing its artifact-parity gap structurally. **Scope: `api` only** — `errors` is deliberately excluded (see *Alternatives*).

> **Numbering:** `web` claimed `ADR-055` globally (2026-06-25); kubelab's next free number is `056`. The decision is independent of the number.

## Context

ADR-046 (D2) established two immutable tag lanes: staging tracks `sha-<short>` (build-on-merge), prod ships clean semver `X.Y.Z` (release-please). It left *how the semver image is produced* implicit, and the implementation rebuilds it:

```
release.yml :: publish-api  (if api_release_created)
  └─ uses ci-publish.yml  →  docker build ./apps/api  →  push kubelab-api:X.Y.Z
```

`ci-publish.yml` is the reusable **build** workflow. So on every release, the prod image is a fresh `docker build` from the release commit. This is the exact defect [ADR-055](ADR-055-semver-everywhere-delivery.md) names: the prod image (a) is built at a different time than staging's — base-layer and transitive-dependency drift — and (b) was never run in staging as those exact bytes. **Prod ships what staging never validated.**

This is not theoretical. The first gated prod promotion (`api` → `1.1.0`, kubelab#664) **CrashLooped in prod** on an init-guard that staging never exercised (incident #666), precisely because staging ran a different artifact than the rebuilt `1.1.0`. kubelab#679 tracks the process gap; its originally-proposed fix was a *manual* "validate the candidate semver on staging before promoting" runbook step. That workaround adds ceremony and still relies on human discipline.

ADR-055 solved this for the extracted `web` repo (build-once / promote-by-digest), verified: `kubelab-web:1.2.0` digest == `:sha-60b24e7` (identical manifest list). But ADR-055's scope note "kubelab unchanged" refers to kubelab's **GitOps/manifest** side (consuming web's tag); it does **not** cover kubelab's own app builds. Those still rebuild. With `web` on build-once and `api` rebuilding, the platform has **two divergent delivery patterns for its products** — exactly the ambiguity the ADR-053 §5 golden-path template must not inherit. Converging `api` onto build-once closes that gap; `errors` is a different category (edge furniture, not a product — see *Alternatives*) and is left as-is.

## Decision

**On `release_created` for `api`, produce the semver image by re-tagging the staging-validated `sha-<short>` digest — never by rebuilding.**

### D1 — Re-tag, don't rebuild

`release.yml` `publish-<app>` stops calling `ci-publish.yml` (build). Instead it re-tags the validated digest, preserving the multi-arch manifest list:

```
docker buildx imagetools create -t kubelab-<app>:X.Y.Z kubelab-<app>:sha-<short>
```

The bytes Argo CD runs in prod are then the exact bytes validated in staging — build-once, by construction. `promote-prod.yml` is **unchanged**: it still promotes an existing immutable semver tag and refuses a non-existent one.

### D2 — Which digest: the staging-pinned sha (Option B1)

The `sha-<short>` to re-tag is resolved from the **staging SSOT** — `apps.platform.<app>.version` in `infra/config/values/staging.yaml`, the artifact a human last validated on staging — via a first-class toolkit command (`toolkit deployment image-tag --env staging --app <app>`), never hardcoded and never the release-bump commit's sha.

Rejected alternative **B2** (consolidate build+release so the release commit's own sha is re-tagged, as `web` does): in an extracted single-app repo the release commit *is* the validated push, so B2 is correct there. In the monorepo the release-PR merge is a **different commit** (a version-bump touching only `version.txt`/CHANGELOG) than the one validated in staging — re-tagging its sha would re-introduce an unvalidated artifact. B1 ties prod to the SSOT-declared staging artifact, which is the honest parity guarantee #679 demands. Reuses the `values/<env>.yaml` → `toolkit` → drift-gate (ADR-027) machinery already in place.

### D3 — Protect the validated digest from pruning

`ci-cleanup.yml` prunes old `sha-*` tags. It must never prune a sha referenced by a committed overlay (the one pending or live in an environment). The re-tag runs at `release_created` (ahead of any prune window); additionally the cleanup excludes any `sha-*` currently pinned in a `values/<env>.yaml`. This makes the parity guarantee robust against tag-lifecycle races.

## Consequences

**Positive**
- Dissolves #679 structurally: prod runs the staging-validated bytes by construction — no manual candidate-semver validation step, no reliance on runbook discipline.
- One delivery pattern across the whole platform (`web`, `api`, `errors`) → the ADR-053 golden-path template is correct when distilled.
- Supply-chain property (prod == validated staging digest) — a SLSA-adjacent, demonstrable maturity signal.
- Removes one `docker build` per release (the rebuild); release is now a cheap manifest re-tag.

**Negative / accepted**
- B1 assumes staging is at the release point. True under ADR-046's "promote frequently in small increments"; if staging lags, the operator promotes staging to the release artifact first (the same precondition #679 already wanted, now explicit and tooled).
- A new toolkit subcommand + a `ci-cleanup` guard to maintain. Small, and reuses existing values-loading.

## Alternatives Considered

- **B2 — re-tag the release commit's own sha (web's consolidated form).** Correct for an extracted single-app repo; wrong for the monorepo where the release-bump commit ≠ the validated commit. Rejected (see D2).
- **Keep rebuilding (status quo / ADR-046 D2 literal).** The defect that CrashLooped prod (#666). Rejected.
- **Manual candidate-semver validation runbook (#679's original proposal).** A process workaround that build-once makes unnecessary. Superseded.
- **Digest-pinned manifests (`@sha256:…`).** Maximally immutable but costs manifest readability and adds tag→digest resolution to promote tooling. ADR-055 declined it for the same reasons; immutable tags + re-tag already give build-once. Out of scope.
- **Apply build-once to `errors`, or extract `errors` to its own repo like `web`.** Both rejected. `errors` (`edge/errors/` — 369 lines of static HTML served by nginx) is **edge infrastructure, not a product**: no independent identity / users / brand, tightly coupled to the Traefik `error-pages` middleware and the VPS Traefik templates that live in kubelab. ADR-053 / ADR-048 are *product* boundaries — extracting `errors` would create a repo with more CI/governance than content, cargo-culting the `web` extraction onto a different category. And build-once's value for it is near-zero: static pages have no init-guards, no runtime deps, a pinned base image (`nginx:1.31-alpine`), and no staging validation to lose (the #666 CrashLoop was `api`, never `errors`). `errors` stays in kubelab on its existing release-build. Reassess only if it ever gains product-like identity/cadence.

## Implementation

Sequenced as independently-mergeable PRs (this ADR is PR-1, decision-only):

1. **PR-1 (this ADR) + spec `DELIVERY-002-build-once-apps`.** Decision, no code.
2. **PR-2 — build-once.** `toolkit deployment image-tag` (resolver + unit test); `release.yml` `publish-<app>` → re-tag instead of `ci-publish.yml`; `ci-cleanup.yml` prune guard; runbook update. Verified by digest equality (`<app>:X.Y.Z` == `:sha-<short>`).

The CalVer "Global Release Bundle" (`ci-release.yml`) divergence from release-please-as-sole-semver-authority is **out of scope** (separate audit ticket); progressive delivery is DELIVERY-001 (#373); `errors` build-once / extraction is out of scope (see *Alternatives*).

## References

- [ADR-055](ADR-055-semver-everywhere-delivery.md) (`web` repo) — the pattern this extends; verified `kubelab-web:1.2.0` == `:sha-60b24e7`.
- [adr-046-gitops-delivery-promotion-strategy](adr-046-gitops-delivery-promotion-strategy.md) — D2 (two immutable lanes) refined here.
- [adr-027-config-drift-gate](adr-027-config-drift-gate.md) — guarantees overlays == generator output; the re-tag flows through the same SSOT.
- kubelab#679 (artifact parity), #666 (the CrashLoop incident), #678 (ARGO-016 epic), #373 (DELIVERY-001, next level).
