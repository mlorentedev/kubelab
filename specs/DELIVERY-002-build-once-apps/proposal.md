---
id: "DELIVERY-002-build-once-apps"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-06-26"
issue: "mlorentedev/kubelab#679"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, delivery, gitops, ci-cd, versioning]
template_version: "1.0"
---

# DELIVERY-002-build-once-apps

> Extends [[adr-055-semver-everywhere-delivery|ADR-055]] (shipped for the extracted `web` repo) to kubelab's own monorepo apps. Closes the structural half of [[adr-046-gitops-delivery-promotion-strategy|ADR-046]] artifact parity. Tracks kubelab#679.

## Why

<!-- from issue #679: ARGO: staging must run the candidate immutable build, not :dev (artifact parity) -->

The first gated prod promotion (`api` → `1.1.0`, kubelab#664) CrashLooped on an init-guard that **staging never exercised** — because the `1.1.0` image prod ran was a *rebuild* from the release commit, not the artifact validated in staging (#679, incident #666). Today `release.yml` still does this: on `release_created`, `publish-api`/`publish-errors` call `ci-publish.yml`, which **rebuilds** the semver image (`docker build`) from the release commit. That image is built at a different time than staging's (base-layer/transitive-dep drift) and was never run in staging as those exact bytes — so prod ships something staging never validated. ADR-055 fixed exactly this for the extracted `web` repo (build-once / promote-by-digest, verified `kubelab-web:1.2.0` == `:sha-60b24e7`); this spec extends that fix to kubelab's `api` image, converging the platform's products onto one delivery pattern before the ADR-053 golden-path template is distilled. **`errors` is out of scope** — it is edge infrastructure, not a product, and is not on the platform staging-sha lane (see *Out of scope*).

## What

After this PR, when release-please cuts `api:X.Y.Z`, the prod image is produced by **re-tagging the staging-validated `sha-<short>` digest** (`docker buildx imagetools create -t <img>:X.Y.Z <img>:sha-<short>`), **never a rebuild**. The semver tag and the staging sha tag resolve to the **identical digest** (multi-arch manifest list preserved, amd64+arm64). No `docker build` runs at release time for `api`. The sha to re-tag is resolved from the staging SSOT (`apps.platform.api.version` in `infra/config/values/staging.yaml`) — the artifact a human last validated on staging — not hardcoded and not the release-bump commit. `promote-prod.yml` is unchanged: it still promotes an existing immutable semver tag; only *how that tag is produced* changes.

## Out of scope

- **`errors` (`edge/errors/`)** — edge infrastructure (369 lines of static HTML → nginx, coupled to the Traefik `error-pages` middleware), **not a product**, and not on the platform staging-sha lane (`promotion.py` rejects it; `staging-deploy.yml` only filters `apps/api/**`). Build-once's value for static pages is near-zero (no init-guards, no runtime deps, pinned base image, no staging validation to lose). Stays in kubelab on its existing release-build. Neither extracted (ADR-053/048 are product boundaries) nor given build-once. Rationale recorded in ADR-056 *Alternatives*.
- **CalVer "Global Release Bundle" (`ci-release.yml`)** — its divergence from ADR-046's release-please-as-sole-semver-authority is real conceptual debt, but orthogonal to build-once; it ships no bad bytes. Separate audit ticket.
- **Argo Rollouts / progressive delivery** — DELIVERY-001 (#373), the next level beyond build-once.
- **Digest-pinned manifests (`@sha256:…`)** — ADR-055's "optional hardening, not adopted"; immutable tags + re-tag already give build-once.
- **The `web` repo** — already ADR-055-compliant.
- **Changing the staging lane** — `staging-deploy.yml` already builds + promotes immutable `sha-<short>` (ADR-046 D2); unchanged here.

## Risks / open questions

- **[OPEN — the ADR-056 decision] Which digest to re-tag.** Two viable mechanisms:
  - **B1 (recommended):** re-tag the sha currently pinned in `values/staging.yaml` (`apps.platform.<app>.version`) — the exact artifact a human validated on staging. Strongest parity; assumes staging is at the release point (true for the small-increment promotion cadence ADR-046 prescribes).
  - **B2 (web's form):** consolidate build+release so the release commit's own sha is re-tagged. Simpler ordering, but the release-bump commit's image was not independently validated. Rejected for the monorepo — weaker parity, and the release-PR merge is a *different* commit than the one validated.
- **[RISK] Prune race.** `ci-cleanup.yml` prunes old `sha-*` tags. The sha pending prod promotion must not be pruned before its semver re-tag exists. Mitigation: re-tag at `release_created` (before any prune window), and/or never prune a sha referenced by a committed overlay.
- **[RISK] `imagetools create` must preserve the multi-arch manifest list** (it copies the manifest, not a single arch) — assert in verification by inspecting both tags resolve to the same `sha256` manifest-list digest.
- **[DEP] Registry auth in `release.yml`** — the re-tag step needs Docker Hub login (already present for builds); no new secret.

## Acceptance criteria

Observable outcomes. Each must be testable.

- [ ] On `release_created` for `api`, **no `docker build`** runs for the semver tag — the semver image is produced solely by re-tagging an existing `sha-<short>` digest.
- [ ] `kubelab-api:X.Y.Z` resolves to the **same manifest-list digest** as the staging-validated `kubelab-api:sha-<short>` (identical amd64 + arm64).
- [ ] The sha to re-tag is **resolved from the staging SSOT** (`values/staging.yaml`), never hardcoded — covered by a toolkit unit test reading the SSOT.
- [ ] `promote-prod.yml` behavior is unchanged (still refuses a non-existent registry tag; still opens a gated PR).
- [ ] A toolkit command resolves the staging-pinned sha for an app and is unit-tested without network/registry access.

## References

- Bitácora board: kubelab#679 (artifact parity); parent epic kubelab#678 (ARGO-016 / ADR-046).
- Related ADR: `docs/adr/adr-056-build-once-monorepo-apps.md` (this spec's decision); extends `web` `docs/adr/ADR-055-semver-everywhere-delivery.md`; refines `docs/adr/adr-046-gitops-delivery-promotion-strategy.md`.
- Related: DELIVERY-001 (#373, Argo Rollouts — next level); incident #666 (the CrashLoop that spawned #679).
