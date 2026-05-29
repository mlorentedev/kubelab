---
id: adr-021-helm-k8s-packaging
type: adr
status: active
created: "2026-03-15"
owner: manu
---

# ADR-021: Helm as K8s Workload Packaging — Hybrid Chart Strategy

## Status

**Revised (2026-03-19)**: Changed from all-Helm to hybrid strategy. Custom apps stay in Kustomize (simpler, WYSIWYG YAML). Third-party services migrate to official Helm charts. ArgoCD supports both natively. Original acceptance: 2026-03-16.

## Context

K8s workloads are currently deployed via raw YAML manifests (`infra/k8s/base/` + `infra/k8s/overlays/`) applied with `kubectl apply -k`. This approach has accumulated significant technical debt:

1. **SSOT violation**: ~80 hardcoded domains, ~11 hardcoded image versions, ~6 hardcoded IPs across manifests. Values exist in `common.yaml` but don't flow into K8s YAML (audit 2026-03-16).
2. **Drift risk**: Changing a domain in `common.yaml` doesn't update K8s manifests. Manual sync required across base + overlays.
3. **No versioning**: Raw manifests have no release concept. Rollback = `git revert` + `kubectl apply`.
4. **ArgoCD blocked**: Stream E requires a packaging format ArgoCD can manage. Raw manifests work but Helm provides richer lifecycle (diff, rollback, hooks, dependencies).

### Options evaluated

| Option | Resolves SSOT | ArgoCD path | Skill signal | Effort |
|--------|:---:|:---:|:---:|:---:|
| **A: Helm (hybrid)** | Yes | Direct | High (industry standard) | Medium |
| **B: Toolkit K8s generator** | Yes | Via Kustomize | Low (custom, throwaway) | Medium |
| **C: Kustomize replacements (v4+)** | Partial | Yes | Low | Low |
| **D: Keep raw manifests** | No | Limited | None | None |

### Why not a custom generator (Option B)?

The toolkit already has an Ansible inventory generator (`generator_ansible.py`). Extending it for K8s was considered, but this would be throwaway work — ArgoCD (Stream E) needs Helm or Kustomize as source, not generated YAML from a custom tool. Investing in Helm is the investment that compounds.

## Decision

### 1. Hybrid Helm strategy: official charts + generic app chart

Two categories of workloads, two approaches:

**Third-party services → consume official Helm charts**

Services with mature Helm charts maintained by their vendors. We write zero templates — only `values-{env}.yaml` overrides.

| Service | Chart | Repository |
|---------|-------|------------|
| Grafana | `grafana/grafana` | https://grafana.github.io/helm-charts |
| Loki | `grafana/loki` | https://grafana.github.io/helm-charts |
| Authelia | `authelia/authelia` | https://charts.authelia.com |
| CrowdSec | `crowdsec/crowdsec` | https://crowdsecurity.github.io/helm-charts |
| MinIO | `minio/minio` | https://charts.min.io |
| n8n | `open-source-labs/n8n` | https://n8n-io.github.io/n8n-helm-charts |
| Gitea | `gitea/gitea` | https://dl.gitea.io/charts |
| Redis | `bitnami/redis` | https://charts.bitnami.com/bitnami |

**Custom apps → one generic reusable chart**

A single `kubelab-app` chart that deploys any container with: Deployment, Service, IngressRoute (Traefik CRD), ConfigMap, optional HPA. Values files per app per env.

Apps using the generic chart: `api`, `web`, `errors`, `vector`.

### 2. Umbrella chart for orchestration

A top-level umbrella chart declares all sub-charts as dependencies. Single `helm upgrade` deploys the full stack.

```
infra/helm/kubelab/
  Chart.yaml                    # Umbrella — declares dependencies
  values.yaml                   # Global defaults (maps to common.yaml structure)
  values-staging.yaml           # Staging overrides
  values-prod.yaml              # Prod overrides
  charts/
    kubelab-app/                # Generic app chart (local)
      Chart.yaml
      templates/
        deployment.yaml
        service.yaml
        ingressroute.yaml       # Traefik CRD
        configmap.yaml
      values.yaml
```

Official charts are declared as dependencies in `Chart.yaml`, not vendored:

```yaml
dependencies:
  - name: grafana
    version: "8.x.x"
    repository: https://grafana.github.io/helm-charts
    condition: grafana.enabled
  - name: loki
    version: "6.x.x"
    repository: https://grafana.github.io/helm-charts
    condition: loki.enabled
  # ... etc
```

### 3. Values structure mirrors common.yaml

The umbrella `values.yaml` follows the same hierarchical structure as `common.yaml`. This makes the mapping explicit and eliminates the SSOT problem:

```yaml
global:
  baseDomain: kubelab.live
  timezone: Europe/Madrid

apps:
  api:
    image:
      repository: docker.io/mlorentedev/kubelab-api
      tag: dev
    domain: api.staging.kubelab.live
    port: 8080

grafana:
  enabled: true
  ingress:
    hosts:
      - grafana.staging.kubelab.live
```

Environment overrides (`values-prod.yaml`) contain only the deltas — same pattern as `prod.yaml` overriding `common.yaml`.

### 4. Deploy method

```bash
# Staging
helm upgrade --install kubelab ./infra/helm/kubelab \
  -f values.yaml -f values-staging.yaml -n kubelab --create-namespace

# Prod
helm upgrade --install kubelab ./infra/helm/kubelab \
  -f values.yaml -f values-prod.yaml -n kubelab --create-namespace
```

Makefile target:
```bash
make helm-deploy ENV=staging   # Replaces make k8s-apply
```

### 5. Migration path: incremental, service by service

No big-bang migration. Services migrate one at a time:

1. Create values entry for the service in the umbrella chart
2. `helm upgrade` deploys the Helm-managed version
3. Delete the old raw manifest from `infra/k8s/`
4. Verify — at no point do both the raw manifest AND Helm manage the same resource

**Phase H1** (prerequisite for B6): `errors`, `api`, `web` + umbrella structure
**Phase H2** (before B6): all third-party services via official charts
**Phase H3** (B6): prod deploy uses Helm. Delete `infra/k8s/base/` and `infra/k8s/overlays/`
**Phase H4** (Stream E): ArgoCD Application points to umbrella chart

### 6. Relationship to Ansible

Clear boundary:

| Layer | Tool | Scope |
|-------|------|-------|
| OS/provisioning | Ansible | K3s install, Tailscale, Docker, SSH, firewall |
| Infra services (non-K8s) | Ansible | Headscale, CoreDNS (RPi4), VPS Traefik |
| K8s workloads | Helm | All pods, services, ingress inside the cluster |
| GitOps | ArgoCD (future) | Auto-sync Helm releases from Git |

Ansible **never** runs `kubectl` or `helm`. Helm **never** manages OS-level config. The only shared touchpoint is the SSOT (`common.yaml` → Ansible vars AND Helm values).

### 7. What stays in Kustomize (Revised 2026-03-19)

**Custom apps (api, web, errors)** stay in Kustomize. These are simple Deployment+Service+IngressRoute manifests — Helm templating adds overhead without value. Adding a new app = one more YAML file, no chart maintenance.

**Third-party services** migrate to official Helm charts (H2). These have complex configs where vendor-maintained charts provide significant value (battle-tested templates, documented values, community support).

**Rationale for hybrid over all-Helm**: The generic `kubelab-app` chart (H1) replicated what Kustomize already does well for simple apps. Maintaining custom chart templates is unnecessary overhead for a small team. ArgoCD supports both Kustomize and Helm Applications natively — no penalty for the hybrid approach.

Layout after H2:
- `infra/k8s/base/` + `infra/k8s/overlays/` — custom apps + cluster config (Kustomize)
- `infra/helm/` — third-party service values only (official charts as dependencies)
- `infra/helm/kubelab/` (umbrella + generic app chart) — **deleted** (2026-03-19)

## Rationale

### Why hybrid over all-custom charts?

Writing Helm charts for Grafana, Loki, or Authelia is NIH. These projects invest significant effort in their official charts — battle-tested, documented, community-maintained. Our value-add is the `values.yaml` configuration, not the templates.

The generic `kubelab-app` chart for custom apps avoids the opposite problem: one chart per app when they're structurally identical (Deployment + Service + IngressRoute).

### Why not defer to post-B6?

Migrating prod with raw manifests means migrating hardcoded YAML, then re-migrating to Helm later. Two migrations for the same services. Doing Helm first means B6 deploys with the final packaging format.

### Industry validation

The hybrid pattern (official charts + generic app chart + umbrella) is standard practice:
- Datadog, GitLab, and Elastic all publish official charts consumed via dependencies
- Generic app charts (like `bjw-s/app-template` or `stakater/application`) are widely used
- Umbrella charts with `dependencies:` in Chart.yaml is the Helm-native composition model

## Consequences

1. **Kustomize removed** — `infra/k8s/base/` and `infra/k8s/overlays/` deleted after full migration
2. **New directory** — `infra/helm/kubelab/` becomes the K8s packaging source of truth
3. **Helm CLI required** — `helm` added to developer setup prerequisites
4. **Chart versioning** — umbrella chart follows project CalVer; sub-chart pins follow upstream
5. **SOPS integration** — Helm values files can reference SOPS-decrypted secrets via `helm-secrets` plugin or pre-decryption in Makefile
6. **ArgoCD unblocked** — Stream E can start immediately after H3 (ArgoCD Application → umbrella chart)
7. **common.yaml remains SSOT** — but its values are now consumed by BOTH Ansible (playbook vars) and Helm (values.yaml). Keeping them in sync is a manual step until a generator bridges them.

## Related

- [adr-011-k3s-homelab-staging](adr-011-k3s-homelab-staging.md) — Original deploy method decision (`kubectl apply`, ArgoCD deferred)
- [adr-015-vps-k3s-migration-strategy](adr-015-vps-k3s-migration-strategy.md) — B6 migration strategy (Pattern C, Headscale stays in Compose)
- [adr-020-iac-lifecycle-strategy](adr-020-iac-lifecycle-strategy.md) — Ansible roles for provisioning (boundary with Helm clarified here)
- Stream E tasks (ARGO-001..006, SEAL-001..004) — ArgoCD + Sealed Secrets, post-Helm
