---
id: "kubelab-architecture-versioning-strategy"
type: architecture
status: active
tags: [kubelab, ci-cd, versioning]
created: "2026-02-21"
updated: "2026-08-12"
owner: manu
---

# Versioning Strategy

KubeLab versions each deployable component independently via [release-please](https://github.com/googleapis/release-please), driven by [Conventional Commits](https://www.conventionalcommits.org/). There is no global version — see [ADR-059](../adr/adr-059-retire-calver-release-bundle.md) for why a repo-wide CalVer bundle was retired rather than kept alongside it.

## What gets a semver release

release-please tracks two components in this repo (`release-please-config.json`), matching [ADR-046](../adr/adr-046-gitops-delivery-promotion-strategy.md) D2 (sole semver authority) and the pin-vs-HEAD rule from ADR-059 (a component gets a release only if something references it by a fixed version):

| Component | Path | Tag prefix | Consumer that pins to it |
|---|---|---|---|
| `api` | `apps/api/` | `api-v` | `infra/k8s/base/kustomization.yaml` image tag |
| `errors` | `edge/errors/` | `errors-v` | `infra/k8s/base/kustomization.yaml` image tag |

`infra/` and `toolkit/` are applied at git `HEAD` (Argo CD sync, `poetry run toolkit`) — nothing pins to a version of either, so they have no release-please package. `web` also carries an independent semver, but its source and release-please config live in its own repo (`mlorentedev/web`, extracted per [ADR-053](../adr/adr-053-platform-product-repos.md)) — only its *deployment* (staging/prod version pins) is tracked here, promoted the same way `api` is (see [gitops-delivery-promotion.md](../runbooks/gitops-delivery-promotion.md)).

## Version bump rules (Conventional Commits)

| Commit prefix | Bump | Example |
|---|---|---|
| `fix:` | Patch (x.y.**Z**) | `fix: resolve auth timeout` |
| `feat:` | Minor (x.**Y**.0) | `feat: add user profile API` |
| `feat!:` or `BREAKING CHANGE` footer | Major (**X**.0.0) | `feat!: change API response format` |
| `docs:`, `chore:`, `style:`, `refactor:`, `ci:` | None | `docs: update README` |

Only commits touching a component's own path (`apps/api/**`, `edge/errors/**`) count toward its bump — `separate-pull-requests: false` still accumulates both into one combined release-please PR when both have pending changes, but the version math per component stays isolated (a commit under `apps/api/` never bumps `errors`, or vice versa).

## Docker image tag lifecycle

There is no RC scheme (`-rc.N` was dropped — see `ci-cleanup.yml`'s comment and the janitor's own retention logic).

| Stage | Tag | Produced by | Mutable? |
|---|---|---|---|
| Feature/fix/hotfix/chore branch (pre-merge preview) | `sha-<short>` | `ci-pipeline.yml` → `ci-publish.yml` on the PR | No — one tag per commit |
| Staging (continuous, every merge to `master`) | `sha-<short>` | `staging-deploy.yml` (`api`) / `web-image-receiver.yml` (`web`, cross-repo dispatch) | No |
| Prod (`api`) | `X.Y.Z` + `:latest` | `release.yml`'s `publish-api` job — **re-tags** the staging-validated `sha-<short>` digest, never rebuilds ([ADR-056](../adr/adr-056-build-once-monorepo-apps.md), build-once) | No |
| Prod (`errors`) | `X.Y.Z` | `release.yml`'s `publish-errors` job — rebuilds; `errors` is edge infra, explicitly out of the build-once staging-sha lane | No |
| Prod (`web`) | `X.Y.Z` | Built in `mlorentedev/web`'s own CI, promoted here via `promote-prod.yml` | No |

Build-once parity (`api` only) is verified in-job by comparing the staging and prod tag's manifest-list digest — a mismatch fails the release rather than silently shipping unvalidated bytes.

## How a release actually ships

This is release-please's job (cut the tag + changelog + Docker artifact); **getting that artifact into staging or prod is a separate, deliberate step** — see [gitops-delivery-promotion.md](../runbooks/gitops-delivery-promotion.md) for the full model. Two shapes exist:

- **`api`/`web`**: staging tracks every merge automatically (an auto-opened PR, human merges); prod is promoted manually via the `promote-prod.yml` `workflow_dispatch` (pick app + version, human merges the resulting PR).
- **`errors`**: `release.yml`'s `promote-errors` job auto-opens a PR pinning the new tag — one version, both environments (`edge.errors.version` is a single env-agnostic SSOT, [DELIVERY-003](https://github.com/mlorentedev/kubelab/issues/776)) — a human still merges it, but there's no separate staging step and no manual dispatch.

None of this auto-commits to `master` directly — `master` is protected; every version change lands as a reviewed PR (ADR-046 D3/D6).

## No global release bundle

`ci-release.yml` (the CalVer `vYYYY.MM.DD` + zip bundle described in earlier versions of
this doc) was retired — see
[ADR-059](../adr/adr-059-retire-calver-release-bundle.md). Nothing in the repo pinned to it,
and its `make deploy` instructions predated the K3s/Argo CD GitOps deploy path. `infra/` and
`toolkit/` are applied at git `HEAD` and have no release of their own — see ADR-059 for the
pin-vs-HEAD rationale and the optional showcase-release follow-up.

## Current baseline

`api-v*` and `errors-v*` tags exist and are cut by release-please as described above. `web-v*`
tags remain from before the `web` app was extracted to its own repo (ADR-048) and are not
produced here anymore.

## Workflow files (versioning-relevant)

| File | Role |
|---|---|
| `ci-pipeline.yml` | Per-PR: builds the `sha-<short>` preview tag for the changed app(s) |
| `release.yml` | release-please: cuts `api-vX.Y.Z`/`errors-vX.Y.Z`, re-tags (`api`) or rebuilds (`errors`), auto-promotes `errors` |
| `staging-deploy.yml` / `web-image-receiver.yml` | Continuous staging promotion (`api` / `web`) |
| `promote-prod.yml` | Manual gated prod promotion (`api`/`web`) |
| `ci-cleanup.yml` | Weekly janitor — prunes old `sha-*` tags, never touches prod semver |

Full pipeline (validation, security scanning, drift gates, board automation) is in
[cicd.md](../runbooks/cicd.md).

## Best practices

1. **Always use Conventional Commits** — they drive every version bump automatically; a commit
   with the wrong prefix either doesn't bump when it should, or bumps the wrong number.
2. **Keep feature/fix/hotfix/chore branches short-lived** — `master` is the only permanent
   branch (trunk-based); there is no `develop` to stage work in.
3. **Never hand-create a version tag or edit `.release-please-manifest.json`'s tracked
   versions** — let release-please own both; a manual edit fights the next release PR.
4. **A merged release-please PR is not a deploy** — the code was already on staging from its
   original feature-branch merge; release-please just cuts the prod-ready semver. Prod itself
   always needs the explicit `promote-prod.yml` dispatch (`api`/`web`) or the auto-opened
   `promote-errors` PR merge (`errors`).
5. **Monitor Docker tags** — only `kubelab-*` image repos should exist on the registry; the
   weekly `ci-cleanup.yml` prune keeps `sha-*` tag counts bounded.
