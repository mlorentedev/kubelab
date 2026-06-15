---
id: "adr-046-gitops-delivery-promotion-strategy"
type: adr
status: accepted
created: "2026-06-14"
tags: [architecture, gitops, argocd, environment-promotion, ci-cd, versioning, stream-c]
related:
  - adr-037-environment-promotion-strategy
  - adr-027-config-drift-gate
  - adr-023-hub-spoke-multicloud-gitops
  - adr-030-self-hosted-runner
issue: "mlorentedev/knowledge#94"   # ARGO-016 epic
---

# ADR-046: GitOps Delivery & Promotion Strategy

## Status

Accepted — 2026-06-14

Extends and **supersedes the mechanism** of [ADR-037](adr-037-environment-promotion-strategy.md) "Pattern D — Image Tag Promotion". ADR-037's *goal* (staging auto-tracks, prod promoted by explicit PR) stands; its *assumed mechanism* (`argocd-image-updater`, tracked as the never-filed ARGO-014) is replaced by a CI-driven, controller-free design. ADR-037's reaffirmed decisions (trunk-based / Pattern A rejection; conditional selfHeal) are unchanged.

## Context

ADR-037 (2026-05-23) decided the *what* of environment promotion but deferred the image-promotion *how* to "Pattern D", blocked on `argocd-image-updater` (ARGO-014). Pattern D never landed. A 2026-06-14 investigation found the interim state had drifted into a set of coupled defects:

1. **Both staging and prod overlays reference the same mutable tag `:dev`.** There is no promotion gate: a feature-branch build that overwrites `:dev` would reach prod on its next pull. Staging is not a gate; it runs the same moving pointer as prod. (Live proof: both pods were 78 days old running *different* digests of the same `:dev` tag — `cbb27d06` on staging, `d0283b6f` on prod — while the registry `:dev` had moved to `05ca8837`.)
2. **`imagePullPolicy` is never declared** in the generator (`infra/k8s/templates/deployments.yaml.j2`). Kubernetes then derives it from the tag name (`:latest` → Always, anything else → IfNotPresent). Because the tag is `:dev`, staging silently defaulted to `IfNotPresent` and never re-pulled — defeating the mutable-tag test-bed strategy. This exact failure was already captured as a lesson on 2026-03-16 ("Mutable tags (:dev) require imagePullPolicy Always") but was never enforced in code.
3. **The RC versioning scheme is broken and unused.** `ci-pipeline.yml` predicts an RC version (`1.0.2-rc.396`) that is *semver-behind* the stable version release-please actually cut (`1.1.0`), is numbered by the global workflow run number, and is computed by a mechanism that disagrees with release-please. A staging override meant to use RC tags (`apps.web.version: 0.0.0-rc.0` in `staging.yaml`) was mis-nested under `apps.web` instead of `apps.platform.web`, so it silently did nothing — and the tag did not exist in the registry anyway.

The platform needs a delivery model that is git-honest (running state reflected in git), auditable, gives an explicit human gate before prod, adds **zero runtime footprint to the ~1–2 GB AWS t4g.micro hub**, and scales to every custom app and to future Stream C repos.

## Decision

### D1 — Branching: trunk-based + overlay/tag promotion (reaffirm ADR-037)

`master` remains the only permanent branch. Environments are separated by **Kustomize overlay path** (already in place) plus **image tag**, never by branch. A `dev`/`staging` long-lived branch is **rejected** — it is a documented GitOps anti-pattern (merge conflicts, drift, no clear audit trail) and re-opens ADR-037's Pattern A rejection with no new trigger. Promotion is *bumping an artifact version in the destination overlay*, not merging a branch.

### D2 — Two immutable tag lanes (drop the broken RC scheme)

| Lane | Producer | Scheme | Mutability |
|---|---|---|---|
| **staging / dev** | build-on-merge (CI) | commit SHA: `sha-<short>` | immutable |
| **prod / release** | release-please | clean semver: `1.2.0` | immutable |

The predicted-RC scheme (`X.Y.Z-rc.<run>`) is removed. Staging tags **what was built** (the commit), not a *predicted* next version — eliminating the prediction bug at its root and leaving release-please as the **sole source of semver truth**. Immutable tags everywhere means a tag change is always a real git diff Argo CD can reconcile, and no tag is ever reused.

### D3 — Delivery: Continuous Deployment to staging, Continuous Delivery to prod

- **staging** = Continuous Deployment. On merge to `master`, CI builds `app:sha-<short>`, then bumps the staging overlay's app version (in `values/staging.yaml`) and regenerates + commits. Argo CD auto-syncs → staging always reflects `master` HEAD. No human gate.
- **prod** = Continuous Delivery. The prod overlay pins an immutable semver. Promotion is an **explicit PR** that bumps the prod version (`workflow_dispatch` opens it, or it is hand-authored). A human reviews and merges; rollback is `git revert`. `selfHeal: true` then actively defends the pinned version. **auto-sync ≠ auto-promote**: Argo converges prod to what git says, and git says the last promoted version until a PR changes it.

### D4 — Mechanism: CI-driven, controller-free (supersedes ADR-037 Pattern D)

The image-tag bump is a `kustomize`/value edit committed by GitHub Actions, **not** an in-cluster controller. A 2026-06-14 reference audit of four approaches (argocd-image-updater, Flux Image Automation, Kargo, CI-driven) found CI-driven the best fit for a solo small-hub:

- **Zero hub footprint** — the actor is a GitHub-hosted/self-hosted runner, not a pod on the t4g.micro. (Flux ≈ 192 Mi + OOM spikes and Kargo's 5–6-pod control plane + cert-manager were disqualified on RAM; argocd-image-updater fits but adds a controller for marginal benefit since our CI already knows the tag it built.)
- **Maximally git-honest** — the real overlay is the SSOT, changed via normal commit history. No `.argocd-source-*` override file, no out-of-band mutation.
- **Canonical** — this is the pattern ArgoCD's own best-practices doc and OpenGitOps advocate (separate config from source).
- **Safest for the prod gate** — prod cannot change unless a PR merges; there is no controller to mis-target (cf. argocd-image-updater rollback-override issue #1249).

`argocd-image-updater` is **descoped** to a future option (ticketed), to be revisited only if auto-discovery of images we do **not** build becomes a real need.

### D5 — Explicit, tag-aware `imagePullPolicy` (enforce in the generator)

The generator declares `imagePullPolicy` explicitly, never relying on the Kubernetes tag-name default: mutable tags (`dev`, `latest`, `*-rc.*`) → `Always`; immutable tags (semver, `sha-*`) → `IfNotPresent`. Implemented in `generator_k8s.py::_resolve_pull_policy` + `deployments.yaml.j2`. The config-drift gate (ADR-027) guarantees the committed overlays always equal the generator output, so promotion *must* flow through values → regenerate → commit — the drift gate is the anti-tamper guard by construction.

## Consequences

**Positive**
- Prod regains a real promotion gate, rollback (`git revert`), and an immutable audit trail of exactly what runs.
- The mutable-`:dev` class of bug is dissolved: immutable tags + Argo tag-diff auto-deploy remove the need for `Always` + `rollout restart` on staging once D2/D3 land.
- Zero new runtime on the constrained hub; no new dependency to monitor, secure, or upgrade.
- release-please becomes the single semver authority; the version-prediction bug disappears.
- Scales by repetition to every custom app and Stream C repo (same overlays + same CI pattern).

**Negative / accepted tradeoffs**
- CI needs a scoped git-write credential (deploy key / GitHub App) to commit tag bumps — blast radius must be minimized.
- Build-on-merge adds one image build per merge to `master`; acceptable for a small platform.
- A staging that runs far ahead of prod means a promotion can batch many changes (more risk per release). Mitigation: promote frequently in small increments.
- Promotion logic is hand-rolled YAML with no built-in verification/analysis gates (the Kargo niche) — acceptable for a solo operator.

## Alternatives Considered

- **argocd-image-updater (ARGO-014, the original Pattern D mechanism)** — rejected as the primary mechanism: adds an in-cluster controller for image auto-discovery we don't need (we build our own images), writes a shadow override file (less git-honest), and has a rollback-override footgun. Kept as a future option for third-party-image auto-discovery.
- **Flux Image Automation** — rejected: most git-honest, but 3 controllers + memory spikes bust the hub budget, and ArgoCD coexistence is undocumented DIY.
- **Kargo** — rejected: purpose-built for exactly this staging→prod-PR flow and ideal on a larger cluster, but its 5–6-pod control plane + cert-manager + documented memory blowup disqualify it on a t4g.micro, and its conceptual weight is overkill for one operator with a single promotion hop.
- **Branch-per-environment (dev/staging branches)** — rejected (reaffirms ADR-037 Pattern A): documented GitOps anti-pattern; separation belongs in overlay path + tag, not branches.
- **Keep / fix the `-rc.N` scheme** — rejected: the RC ceremony implies an RC→GA promotion flow we don't run, stays coupled to a version predictor, and was already dead config. SHA tags are simpler and more traceable.

## Implementation

Sequenced as independently mergeable, independently working PRs (no debt left floating):

1. **PR-B (this ADR) — generator foundation.** Explicit tag-aware `imagePullPolicy` (`generator_k8s.py` + `deployments.yaml.j2`); remove the dead mis-nested staging RC override. Effect: staging `:dev` now re-pulls (unblocks WEB-011 verification); prod unchanged (still `:dev`, now explicitly `Always` = matches live). No prod roll.
2. **PR-C — SHA tag scheme + build-on-merge.** `ci-publish.yml`/`ci-pipeline.yml` emit `sha-<short>`; a `push: master` workflow builds + bumps `values/staging.yaml` + regenerates + commits. Staging migrates from mutable `:dev` to immutable SHA (continuous deployment, no `Always` needed).
3. **PR-D — prod promotion workflow.** `workflow_dispatch` (target version) bumps `values/prod.yaml` → regenerate → open PR. First gated promotion: prod `:dev` → `:1.1.0` (current stable), *after* staging validation — dogfooding the gate.
4. **PR-E — cleanup.** `ci-cleanup.yml` prunes old `sha-*` tags; file the descoped `argocd-image-updater` follow-up ticket.

The canonical PR workflow for K8s changes (ADR-037 §Validation) is unchanged: validate on staging, then promote to prod.

## References

- [adr-037-environment-promotion-strategy](adr-037-environment-promotion-strategy.md) — supersedes its Pattern D mechanism; reaffirms Pattern A rejection + conditional selfHeal.
- [adr-027-config-drift-gate](adr-027-config-drift-gate.md) — guarantees generated overlays == generator output (anti-tamper for D5).
- Lessons `docs/lessons.md`: 2026-03-16 "Mutable tags (:dev) require imagePullPolicy Always"; 2026-03-22 "Kustomize images section doesn't cover custom apps automatically".
- 2026-06-14 reference audit (4 image-promotion approaches) and GitOps branching consensus: [Octopus — Stop Using Branches](https://octopus.com/blog/stop-using-branches-deploying-different-gitops-environments), [Codefresh — Model GitOps Environments](https://codefresh.io/blog/how-to-model-your-gitops-environments-and-promote-releases-between-them/), [Cloudogu — Promotion Patterns](https://platform.cloudogu.com/en/blog/gitops-repository-patterns-part-4-promotion-patterns/), [OpenGitOps](https://opengitops.dev/).
- ARGO-014 (descoped) — `argocd-image-updater` follow-up, revisit trigger: need to auto-discover images not built by our CI.
