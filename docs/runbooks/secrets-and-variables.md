---
id: "kubelab-runbook-secrets-and-variables"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-08"
owner: manu
---

# Secrets and Variables

## Overview

Two systems manage secrets for KubeLab:

1. **SOPS + age** — KubeLab service credentials (Authelia, Grafana, MinIO, etc.) → see [sops-and-secrets](sops-and-secrets.md)
2. **Dotfiles** — API tokens and external credentials (DockerHub, GitHub, Cloudflare, etc.) → `~/Projects/dotfiles/`
3. **Dotfiles (file secrets)** — Kubeconfig deployed via `@KUBECONFIG=kubelab.kubeconfig>~/.kube/kubelab.config` in env-mapping.conf. Decrypted automatically at shell startup, env var `KUBECONFIG` points to the deployed file.

GitHub Actions secrets bridge both: CI needs DockerHub tokens (from dotfiles) and may need service secrets (from SOPS) in the future.

## GitHub Actions Secrets (CI/CD)

### Required secrets

| Secret | Source | Permissions needed |
|--------|--------|-------------------|
| `DOCKERHUB_USERNAME` | dotfiles (`dockerhub.username`) | — |
| `DOCKERHUB_TOKEN` | dotfiles (`dockerhub.token`) | Read & Write (minimum) |
| `N8N_WEBHOOK_URL` | n8n instance config | — |
| `N8N_DEPLOY_TOKEN` | n8n instance config | — |

### List current secrets

```bash
gh secret list
gh variable list
```

### Rotate a secret (full workflow)

```bash
# 1. Rotate in dotfiles (single source of truth)
secrets_rotate DOCKERHUB_TOKEN

# 2. Push to GitHub Actions
github-secrets-manager.sh --from-mapping --select DOCKERHUB_TOKEN

# 3. Verify
gh secret list

# 4. Re-run failed CI if needed
gh run rerun <run-id> --failed
```

### Add a new secret

```bash
# 1. Add to dotfiles
secrets_add MY_NEW_TOKEN myservice.token

# 2. Add mapping in dotfiles/sensitive/env-mapping.conf
#    MY_NEW_TOKEN=myservice.token

# 3. Push to GitHub
github-secrets-manager.sh --from-mapping --select MY_NEW_TOKEN

# 4. Reference in workflow as ${{ secrets.MY_NEW_TOKEN }}
```

### Bulk sync (all mapped secrets)

```bash
github-secrets-manager.sh --from-mapping
```

## Toolkit sync (alternative)

The toolkit has a `setup-gh-secrets` command that syncs from SOPS config:

```bash
toolkit credentials setup-gh-secrets dev
```

**Limitation**: This filters by pattern matching (variables with `user`, `host`, `port` in the name are excluded as "public"). For CI secrets like `DOCKERHUB_USERNAME`, use the dotfiles workflow instead.

## Audit trail

Rotations are tracked in `~/Projects/dotfiles/sensitive/.secrets-audit.log`.

## Last tested

2026-02-16
