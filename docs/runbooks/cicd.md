---
id: "kubelab-runbook-cicd"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-08"
owner: manu
---

# CI/CD

## Overview

GitHub Actions CI/CD pipeline for KubeLab. 4 workflow files handle validation, build, Docker publish, and release bundling.

## Prerequisites

- `gh` CLI installed and authenticated
- Access to the `mlorentedev/kubelab` GitHub repository
- Git repository cloned with tags fetched (`git fetch --tags`)
- DockerHub account with valid access token (Read & Write)

## Pipeline Architecture

```
ci.yml (entry point)
├── validate          → yamllint, branch rules, Makefile syntax
├── detect-changes    → dorny/paths-filter (blog, api, web)
└── {app}-pipeline    → calls ci-pipeline.yml per changed app
    ├── semver        → paulhatch/semantic-version (tag prefix: {app}-v)
    ├── app validation → Go vet/build, npm build, Jekyll build
    ├── security scan → gitleaks, bandit, gosec, npm audit
    └── call-publish  → calls ci-publish.yml
        ├── Docker build (multi-arch amd64+arm64)
        ├── Docker push to DockerHub
        ├── Trivy scan → GitHub Security tab
        └── n8n webhook notification

ci-release.yml (triggered by workflow_run after CI succeeds)
├── CalVer tag        → v{YYYY}.{MM}.{DD} (master) or v{...}-rc.{sha} (develop)
├── Deployment ZIP    → Makefile + infra/ + toolkit/ + compose files
└── GitHub Release    → artifact + changelog
```

## Docker Registry

- **Registry**: `mlorentedev/kubelab-{app}` (e.g., `mlorentedev/kubelab-api`)
- **Config variable**: `vars.REGISTRY_PREFIX` (default: `kubelab`)

## Versioning Strategy

| Branch | Docker Tag | Git Tag | Example |
|--------|-----------|---------|---------|
| feature/* | `0.0.0-dev.{sha}` | none | `0.0.0-dev.a1b2c3d` |
| develop | `X.Y.Z-rc.N` | `{app}-v{X.Y.Z}` | `1.2.3-rc.5` |
| master | `X.Y.Z` + `:latest` | `{app}-v{X.Y.Z}` | `1.2.3` |

- Default bump: **patch** (every commit)
- Minor bump: include `(MINOR)` in commit body
- Major bump: include `(MAJOR)` in commit body
- Versioning restarted from `0.0.1` on 2026-02-16 (registry rebrand)

## Change Detection Paths

| App | Triggers on changes to |
|-----|----------------------|
| api | `apps/api/src/**`, `apps/api/go.mod`, `apps/api/go.sum`, `apps/api/Dockerfile`, `infra/stacks/apps/api/**` |
| web | `apps/web/site/**`, `apps/web/Dockerfile`, `infra/stacks/apps/web/**` |
| blog | `apps/blog/jekyll-site/**`, `apps/blog/Dockerfile`, `infra/stacks/apps/blog/**` |

Changes to `infra/config/values/*.yaml` do NOT trigger rebuilds (GitOps pull model).

## Required GitHub Secrets

| Secret | Purpose | How to rotate |
|--------|---------|---------------|
| `DOCKERHUB_USERNAME` | DockerHub login user | `github-secrets-manager.sh --from-mapping --select DOCKERHUB_USERNAME` |
| `DOCKERHUB_TOKEN` | DockerHub push access (Read & Write) | Regenerate at hub.docker.com/settings/security, then `github-secrets-manager.sh --from-mapping --select DOCKERHUB_TOKEN` |
| `N8N_WEBHOOK_URL` | Build notification endpoint | Update in n8n, then `gh secret set N8N_WEBHOOK_URL` |
| `N8N_DEPLOY_TOKEN` | Webhook auth token | Rotate in n8n, then `gh secret set N8N_DEPLOY_TOKEN` |

**Rotation workflow** (using dotfiles):

```bash
# 1. Rotate the secret in dotfiles (decrypts → prompts new value → re-encrypts)
secrets_rotate DOCKERHUB_TOKEN

# 2. Push to GitHub Actions
github-secrets-manager.sh --from-mapping --select DOCKERHUB_TOKEN

# 3. Verify
gh secret list
```

See [sops-and-secrets](sops-and-secrets.md) for KubeLab-specific secrets (Authelia, Grafana, MinIO, etc.).

## Common Operations

### Trigger manual build

```bash
# Trigger CI on current branch
gh workflow run "CI" --ref feature/my-branch

# View workflow status
gh run list --limit 5

# View specific run logs
gh run view <run-id> --log
```

### Verify which apps changed

```bash
# Files changed since last commit
git diff --name-only HEAD~1

# Filter by apps
git diff --name-only HEAD~1 | grep -E "(apps/blog|apps/api|apps/web)"
```

### Debug version calculation

```bash
# View latest tags per app
git tag --sort=-version:refname | grep "api-v" | head -3
git tag --sort=-version:refname | grep "web-v" | head -3
git tag --sort=-version:refname | grep "blog-v" | head -3

# Commits since last tag
git log $(git tag --sort=-version:refname | grep "api-v" | head -1)..HEAD --oneline -- apps/api/
```

### Re-run failed job

```bash
gh run rerun <run-id> --failed
```

### Verify Docker image

```bash
# Check image exists on DockerHub
docker manifest inspect mlorentedev/kubelab-api:0.0.0-dev.abc1234

# Pull and test locally
docker pull mlorentedev/kubelab-api:latest
docker run --rm mlorentedev/kubelab-api:latest
```

## Troubleshooting

### DockerHub login fails (401 Unauthorized)

1. Token expired → regenerate at hub.docker.com/settings/security (permissions: **Read & Write**)
2. Rotate via dotfiles: `secrets_rotate DOCKERHUB_TOKEN`
3. Push to GitHub: `github-secrets-manager.sh --from-mapping --select DOCKERHUB_TOKEN`
4. Re-run workflow: `gh run rerun <run-id> --failed`

### Docker push fails (insufficient scopes)

Token was created with Read-only permissions. Regenerate with **Read, Write, Delete**.

### Version not bumping

- Check `branch` field in semver config matches actual default branch (`master`)
- Ensure tag prefix matches: `{app}-v` (e.g., `api-v1.0.0`)
- Verify `fetch-depth: 0` and `fetch-tags: true` in checkout step

### Trivy SARIF upload fails

- Ensure job has `permissions: security-events: write`
- Uses `github/codeql-action/upload-sarif@v4` (not v3)

### Push rejected after CI GitOps commit

The pipeline auto-commits version updates to `infra/config/values/{env}.yaml` on the same branch (via `stefanzweifel/git-auto-commit-action`). This means after CI runs, the remote has a commit you don't have locally.

```bash
# Always rebase before pushing when CI has run on the branch
git pull --rebase origin <branch-name>
```

This is expected behavior, not an error. The GitOps step updates the values file so deployment configs always reflect the latest built version.

## Rollback

If a bad build was deployed, use the [deployment](../troubleshooting/deployment.md) rollback procedure. For CI pipeline issues:

```bash
git revert <commit-sha>
git push
```

## Workflow Files

- `.github/workflows/ci.yml` — entry point, validation, change detection
- `.github/workflows/ci-pipeline.yml` — build, test, version, security scan
- `.github/workflows/ci-publish.yml` — Docker build + push + Trivy
- `.github/workflows/ci-release.yml` — deployment bundle + GitHub Release

## Branch Protection Rules

### master

| Setting | Value |
|---------|-------|
| Required status checks | `Validate Branch Name`, `Validate Merge Rules` (strict) |
| PR reviews required | Yes (0 approvals — self-managed repo) |
| Enforce admins | Yes |
| Allow force pushes | No |
| Allow deletions | No |

### develop

| Setting | Value |
|---------|-------|
| Required status checks | Strict mode (no specific checks) |
| PR reviews required | No |
| Enforce admins | Yes |
| Allow force pushes | Yes (useful for history cleanup) |
| Allow deletions | No |

### Restore via CLI

```bash
# master
gh api repos/mlorentedev/kubelab/branches/master/protection -X PUT \
  --input - << 'RULES'
{
  "required_status_checks": {"strict": true, "contexts": ["Validate Branch Name", "Validate Merge Rules"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
RULES

# develop
gh api repos/mlorentedev/kubelab/branches/develop/protection -X PUT \
  --input - << 'RULES'
{
  "required_status_checks": {"strict": true, "contexts": []},
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": true,
  "allow_deletions": false
}
RULES
```

### Emergency: Temporarily disable protection

```bash
# Disable (e.g., for git filter-repo force push)
gh api repos/mlorentedev/kubelab/branches/master/protection -X DELETE
gh api repos/mlorentedev/kubelab/branches/develop/protection -X DELETE

# IMPORTANT: Re-enable immediately after using the restore commands above
```

## Last tested

2026-02-28
