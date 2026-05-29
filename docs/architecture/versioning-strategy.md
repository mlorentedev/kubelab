---
id: "kubelab-architecture-versioning-strategy"
type: architecture
status: active
tags: [kubelab, ci-cd, versioning]
created: "2026-02-21"
updated: "2026-02-28"
owner: manu
---

# Versioning Strategy

KubeLab uses **two complementary versioning schemes** that follow industry standards for Gitflow monorepos.

## 1. Per-App Semantic Versioning

Each application (`api`, `blog`, `web`) is versioned independently based on its own commit history. This is the standard approach for monorepos (Google, Uber, Netflix).

**Tool:** `paulhatch/semantic-version@v5` in `ci-pipeline.yml`
**Tag prefix:** `{app}-v` (e.g., `api-v1.2.3`)

### Version by branch

| Branch | Docker Tag | Git Tag | Example |
|--------|-----------|---------|---------|
| `master` | `{version}` + `:latest` | `{app}-v{version}` | `kubelab-api:1.2.3` |
| `develop` | `{version}-rc.{increment}` + `:dev` | None | `kubelab-api:1.2.0-rc.5` |
| `feature/*` | `0.0.0-dev.{sha}` + `:dev` | None | `kubelab-api:0.0.0-dev.a1b2c3d` |

### Version bump rules (Conventional Commits)

| Commit prefix | Bump | Example |
|--------------|------|---------|
| `fix:` | Patch (x.y.**Z**) | `fix: resolve auth timeout` |
| `feat:` | Minor (x.**Y**.0) | `feat: add user profile API` |
| `feat!:` or `BREAKING CHANGE` | Major (**X**.0.0) | `feat!: change API response format` |
| `docs:`, `chore:`, `style:`, `ci:` | None | `docs: update README` |

### Independent versioning

Apps version independently based on changes in their own `apps/{app}/` directory:

```
api: feat: new endpoint    → api-v0.2.0
web: fix: button color     → web-v0.1.1
blog: (no changes)         → (no build, no version bump)
```

### Docker image registry

```
{DOCKERHUB_USERNAME}/kubelab-api:{version}
{DOCKERHUB_USERNAME}/kubelab-blog:{version}
{DOCKERHUB_USERNAME}/kubelab-web:{version}
```

`REGISTRY_PREFIX` defaults to `kubelab` (configurable via GitHub repo variable).

## 2. Global CalVer System Releases

The entire system (infra + apps) gets a global release bundle for deployment tracking.

**Tool:** `ncipollo/release-action@v1` in `ci-release.yml`
**Trigger:** After CI completes on `master` or `develop`

| Branch | Tag | Type | Artifact |
|--------|-----|------|----------|
| `master` | `v{YYYY.MM.DD}` | Latest Release | `kubelab-v{tag}.zip` |
| `develop` | `v{YYYY.MM.DD}-rc.{sha}` | Pre-release | `kubelab-v{tag}.zip` |

The ZIP bundle contains infra config, compose files, toolkit, and a `MANIFEST.txt` with build metadata.

## GitOps Auto-Update

On `master` and `develop`, the CI automatically commits version bumps to config files:

- `master` → updates `infra/config/values/prod.yaml`
- `develop` → updates `infra/config/values/staging.yaml`

Commit format: `chore(infra): update {app} version to {version} [skip ci]`

## Current Baseline (2026-02-28)

All stale tags and releases from pre-restructuring CI were deleted. The versioning starts clean:

- **Per-app baseline:** `0.0.0` (no `{app}-v*` tags exist yet)
- **First stable release:** Will be created on first `develop → master` merge
- **Expected first versions:** `api-v0.1.0`, `blog-v0.1.0`, `web-v0.1.0` (accumulated `feat:` commits)

## Workflow Files

| File | Purpose |
|------|---------|
| `ci.yml` | Orchestrator: validate, detect changes, dispatch per-app pipelines |
| `ci-pipeline.yml` | Per-app: version calculation, build, test, security scan, Docker push, GitOps update |
| `ci-publish.yml` | Reusable: Docker build + push + Trivy scan |
| `ci-release.yml` | Global: system release bundle creation |

## Best Practices

1. **Always use conventional commits** — they drive version bumps automatically
2. **Keep feature branches short-lived** — merge to develop frequently
3. **Delete branches after merge** — prevents zombie tags
4. **Never manually create version tags** — let CI handle it
5. **Monitor Docker tags** — only `kubelab-*` image repos should exist
