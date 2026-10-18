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

## On change: the Argo CD hub (gcp1)

The hub is `gcp1`, a one-VM managed instance group on GCP (ADR-063).

```bash
make tf-gcp-plan            # preview
make tf-gcp-apply           # apply
make gcp1-replace           # recreate the VM: the same path a preemption takes
```

`gcp1-replace` waits for sshd and for cloud-init to finish
(`wait-node-ready`), provisions the node, and repoints prod's Argo CD route at
its new Tailscale IP. Every recreate is a fresh disk, so cloud-init rebuilds the
hub on its own: it installs Argo CD, registers each spoke in `managed_spokes`
from Secret Manager, and applies the Applications. There is no `deploy-apps` or
`register-spoke` step after a recreate. What it restores is what the instance
template embeds: the chart values and the Applications as of the last
`make tf-gcp-apply`, not as of git. A change to
`infra/k8s/argocd/applications/` reaches the live hub through
`make deploy-apps`, and reaches the next recreate only after
`make tf-gcp-apply`. A recreate also rotates the cluster CA, the SSH host key
and the mesh address, so refresh the hub kubeconfig before anything else talks
to the hub: `make fetch-kubeconfig ENV=hub DIRECT=1`. Start, stop and status
are in `docs/runbooks/gcp-hub-bootstrap.md` §8.

`aws1` was destroyed on 2026-08-23. Its Terraform root and the
`networking.aws` block are dormant on purpose, kept for portability: the
`tf-aws-*` targets are not part of operating the hub.

## Deploy: ArgoCD (Helm upgrade)

Ordering vs `deploy-k8s` is **independent** — the two touch disjoint resources.
(An older note here said "always run AFTER `deploy-k8s`"; that was true only while
`overlays/prod/argocd.yaml` was still listed in the prod overlay, which it stopped
being in #152. `deploy-k8s` no longer renders or applies it at all.)

```bash
make deploy-argocd
```

What it does:
1. Deploys Authelia OIDC config to prod
2. Scales down ALL ArgoCD pods (OOM mitigation)
3. Helm upgrade with 10min timeout
4. Runs `make argocd-repoint`, which renders and applies
   `overlays/prod/argocd-endpointslice.yaml` with gcp1's Tailscale IP resolved
   from MagicDNS, via `toolkit infra k8s render-apply` (ADR-047 / TOOL-009 T4)

A recreate of gcp1 is the only event that changes that IP, which is why
`make gcp1-replace` ends with `argocd-repoint` (lesson-375).

The rest of the Argo CD route — the `argocd` Service and the `argo.kubelab.live`
IngressRoute — is **Kustomize-managed** (`overlays/prod/argocd.yaml`, in the
overlay's `resources:`), so changes to it ship via GitOps like any other route.
It was not always: until #970 the whole three-document file sat outside the
overlay because one document held a placeholder, and SEC-004's `rate-limit`
middleware consequently stayed in git, applied to nothing, while `kubelab-prod`
reported `Synced` — a Synced Application says nothing about resources it does not
manage. `tests/test_orphan_manifests.py` enumerates what is still in that
category; `tests/infra/test_rate_limit.py` checks the live cluster rather than
the manifests.

## Recovery: ArgoCD failed Helm upgrade

```bash
make recover-argocd         # auto-detects pending-upgrade/rollback/failed → rollback
make deploy-argocd          # retry
```

If still fails after recovery:
1. Recreate the hub: `make gcp1-replace`
2. Wait for it to finish. It waits for cloud-init, which installs Argo CD; it does not check that Argo CD is ready
3. `make fetch-kubeconfig ENV=hub DIRECT=1`: the recreate rotated the cluster CA
4. `make recover-argocd && make deploy-argocd`
5. **Never retry more than once on a stressed instance**

## Deploy: K8s workloads (Kustomize)

Normally ArgoCD handles this. Manual deploy only if ArgoCD is down:

```bash
make deploy-k8s ENV=staging   # interactive confirmation
make deploy-k8s ENV=prod      # interactive confirmation
```

**Order matters:** `deploy-k8s` first, `deploy-argocd` last (EndpointSlice).

## Deploy: External services & cluster bootstrap

Folded into `make deploy-k8s` (ADR-047 / TOOL-009 — the old `deploy-external` target was removed):

- coredns-custom (RPi4 hairpin DNS) and versioned operators (agent-sandbox) are rendered
  (MagicDNS) + server-side applied via the `cluster_bootstrap` layer.
- External EndpointSlices (pihole / uptime-kuma) ship in the Kustomize base.

```bash
make deploy-k8s ENV=staging   # covers cluster_bootstrap + external EndpointSlices
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
make monitoring-apply CHECK=1 # print the sync plan, write nothing
make monitoring-apply         # push monitor config; refuses a delete without PRUNE=1
make monitoring-export        # export current config to repo
                              # NOTE: export never writes a push monitor's
                              # pushToken. SOPS owns it; the seed is public.
                              # See rpi3-disaster-recovery.md before restoring.
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
# ace2 developer node (ADR-058 D1)
# Provisioned via: make provision NODE=ace2 ENV=staging
```

## Decision tree: What to run when

| Situation | Command |
|-----------|---------|
| Pushed code to master | Nothing — ArgoCD syncs |
| Changed common.yaml values | `make sync-k8s-images` + commit + push |
| Changed SOPS secrets | `make apply-secrets ENV=x` |
| Changed Cloudflare DNS | `make tf-dns-apply` |
| Changed VPS Traefik config | `make deploy TARGET=vps ENV=prod` |
| ArgoCD UI down | `make deploy-argocd` |
| ArgoCD Helm upgrade failed | `make recover-argocd && make deploy-argocd` |
| gcp1 unresponsive | `make gcp1-status`, then `make gcp1-replace` |
| New node to provision | `make provision NODE=x ENV=y` |
| Uptime Kuma config changed | `make monitoring-apply` |
| Need to check pod logs | `make logs SVC=x ENV=y` |
| Authelia session issues | `make flush-sessions ENV=x` |
