---
id: operations
type: runbook
status: active
created: "2026-03-28"
---

# Operations Runbook

> Master reference for all KubeLab deploy flows and operational commands.
> When in doubt, check here first. Updated 2026-03-28.

## Daily: Push code (GitOps)

ArgoCD auto-syncs from master. No manual deploy needed.

```bash
git push   # ArgoCD detects change → syncs staging + prod automatically
```

Verify: `https://argo.kubelab.live` → both Applications should be Synced + Healthy.

## On change: Homepage config

```bash
make sync-homepage          # regenerate config files from SSOT
git add -A && git commit    # commit generated files
git push                    # ArgoCD applies via configMapGenerator hash suffix
```

## On change: Security headers / Traefik middleware

K8s (staging + prod): ArgoCD auto-syncs from Git.

VPS (Docker Compose Traefik): requires manual deploy:
```bash
make deploy TARGET=vps ENV=prod
```

## On change: Cloudflare DNS / Zone settings

```bash
make tf-dns-plan    # preview
make tf-dns-apply   # apply
```

## On change: AWS infrastructure (aws1)

```bash
# Preview
cd infra/terraform/aws && make tf-aws-plan

# Apply (RECREATES instance — ~5 min downtime)
make tf-aws-apply

# After instance recreates:
make fetch-kubeconfig-hub   # auto-accepts new SSH host key
make deploy-argocd          # Helm install + resolve EndpointSlice IP
make deploy-apps            # re-register Applications
make register-spoke ENV=staging
make register-spoke ENV=prod
```

## Deploy: ArgoCD (Helm upgrade)

**Always run AFTER `deploy-k8s`** — overwrites EndpointSlice with resolved IP.

```bash
make deploy-argocd
```

What it does:
1. Deploys Authelia OIDC config to prod
2. Scales down ALL ArgoCD pods (OOM mitigation)
3. Helm upgrade with 10min timeout
4. Resolves aws1 Tailscale IP via MagicDNS
5. Applies EndpointSlice to prod with resolved IP

## Recovery: ArgoCD failed Helm upgrade

```bash
make recover-argocd         # auto-detects pending-upgrade/rollback/failed → rollback
make deploy-argocd          # retry
```

If still fails after recovery:
1. Reboot aws1 from AWS console
2. Wait 2-3 min for K3s to come back
3. `make recover-argocd && make deploy-argocd`
4. **Never retry more than once on a stressed instance**

## Deploy: K8s workloads (Kustomize)

Normally ArgoCD handles this. Manual deploy only if ArgoCD is down:

```bash
make deploy-k8s ENV=staging   # interactive confirmation
make deploy-k8s ENV=prod      # interactive confirmation
```

**Order matters:** `deploy-k8s` first, `deploy-argocd` last (EndpointSlice).

## Deploy: External services (dynamic IPs)

```bash
make deploy-external ENV=staging   # resolves rpi3/rpi4 Tailscale IPs via MagicDNS
```

## Deploy: VPS (Ansible)

```bash
make deploy TARGET=vps ENV=prod
```

## Setup: GitHub webhook (instant sync)

Only needed once per repo. After this, pushes to master trigger ArgoCD sync instantly (no 3min polling).

1. Generate secret: `openssl rand -hex 32`
2. Add to SOPS: `make secrets ENV=common` → `argocd.github_webhook_secret: "<secret>"`
3. `make deploy-argocd` (injects secret)
4. GitHub repo → Settings → Webhooks → Add:
   - URL: `https://argo.kubelab.live/api/webhook`
   - Content-type: `application/json`
   - Secret: same value from step 1
   - Events: Just the push event

## Register spoke in ArgoCD

```bash
make register-spoke ENV=staging
make register-spoke ENV=prod
make deploy-apps              # apply Application manifests
```

## Monitoring: Uptime Kuma

```bash
make monitoring-apply         # push monitor config (TLS expiry, health checks)
make monitoring-export        # export current config to repo
make monitoring-status        # check Uptime Kuma status
```

## Secrets

```bash
make secrets ENV=common       # edit shared SOPS file (Cloudflare, ArgoCD, etc.)
make secrets ENV=staging      # edit staging SOPS
make secrets ENV=prod         # edit prod SOPS
make apply-secrets ENV=prod   # push SOPS → K8s Secrets
make secrets-audit            # detect drift between envs
```

## Credentials

```bash
make credentials-generate ENV=staging   # regenerate all derived credentials
make credentials-generate ENV=prod
make flush-sessions ENV=prod            # force re-authentication after secret change
```

## Observability

```bash
make pods ENV=staging         # list pods
make pods ENV=hub             # list ArgoCD pods
make logs SVC=authelia ENV=prod          # tail logs
make logs SVC=argocd-server ENV=hub FOLLOW=1   # follow logs
```

## Node provisioning

```bash
make provision NODE=ace1 ENV=staging
make provision NODE=rpi3 ENV=prod
make provision NODE=jetson ENV=prod
# Beelink: ANSIBLE-013 (pending)
# ace2 Ollama (IDP-024 ✓ 2026-03-29)
# Docker on ace2 (100.64.0.5:11434), models: qwen2.5-coder:7b + qwen2.5:7b
# Provisioned via: make provision NODE=ace2 ENV=staging
# Health: curl http://100.64.0.5:11434/api/tags
# Via Traefik: curl https://ollama.staging.kubelab.live/api/tags
```

## Decision tree: What to run when

| Situation | Command |
|-----------|---------|
| Pushed code to master | Nothing — ArgoCD syncs |
| Changed Homepage config | `make sync-homepage` + commit + push |
| Changed common.yaml values | `make sync-homepage` + `make sync-k8s-images` + commit + push |
| Changed SOPS secrets | `make apply-secrets ENV=x` |
| Changed Cloudflare DNS | `make tf-dns-apply` |
| Changed VPS Traefik config | `make deploy TARGET=vps ENV=prod` |
| ArgoCD UI down | `make deploy-argocd` |
| ArgoCD Helm upgrade failed | `make recover-argocd && make deploy-argocd` |
| aws1 unresponsive | Reboot AWS console → `make fetch-kubeconfig-hub && make deploy-argocd` |
| New node to provision | `make provision NODE=x ENV=y` |
| Uptime Kuma config changed | `make monitoring-apply` |
| Need to check pod logs | `make logs SVC=x ENV=y` |
| Authelia session issues | `make flush-sessions ENV=x` |
