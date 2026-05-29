---
id: "adr-014-secrets-management"
type: adr
status: active
tags: [security, secrets, sops, sealed-secrets, gitops]
created: "2026-02-26"
owner: manu
---

# ADR-014: Secrets Management Strategy

## Status

Accepted

## Context

KubeLab needs a secrets management strategy for K8s deployments across staging and prod environments. The project already uses SOPS (age-encrypted YAML) for storing secrets at rest, and a custom toolkit CLI (`toolkit infra k8s apply-secrets`) that decrypts SOPS and creates K8s Secrets via `kubectl`.

The challenge: how should secrets flow from encrypted storage into the K8s cluster, especially for prod?

### Options Considered

| Option | Pros | Cons |
|--------|------|------|
| **Plaintext in overlay** | Simple, single `kubectl apply -k` | Secrets in Git plaintext |
| **SOPS + toolkit CLI** | Already built, no new deps, secrets never in Git plaintext | Imperative step before deploy, not GitOps-native |
| **Bitnami Sealed Secrets** | GitOps-native, encrypted CRDs in Git, ArgoCD-compatible | Requires controller in cluster, `kubeseal` CLI, migration effort |
| **External Secrets Operator** | Enterprise-grade, pulls from Vault/AWS SM/GCP SM | Requires external secret store, overengineered for single-node |
| **KSOPS (Kustomize + SOPS)** | Kustomize-native, reuses existing SOPS keys | Plugin management, fragile across kustomize versions |

## Decision

**Two-phase approach:**

### Phase 1 (Now — B6 prod migration)
Use **SOPS + toolkit CLI** for secrets management.

- Secrets stored encrypted in `infra/config/secrets/{env}.enc.yaml` (SOPS + age)
- `toolkit infra k8s apply-secrets --env prod` decrypts and creates K8s Secrets
- Prod overlay `kustomization.yaml` does NOT include a plaintext `secrets.yaml`
- Deploy workflow: `apply-secrets` first, then `kubectl apply -k overlays/prod/`

### Phase 2 (Stream E — after ArgoCD)
Migrate to **Bitnami Sealed Secrets** for full GitOps-native secrets.

- Sealed Secrets controller in cluster decrypts SealedSecret CRDs
- Encrypted secrets live in Git as CRDs (safe to commit)
- ArgoCD auto-syncs secrets alongside manifests — single declarative deploy
- `toolkit apply-secrets` retired, SOPS kept as backup/migration tool

## Rationale

- **Phase 1** avoids overengineering. The toolkit pipeline mirrors what CI/CD systems do in production (decrypt → inject → apply). No new dependencies needed.
- **Phase 2** is the natural evolution once GitOps (ArgoCD) is in place. Sealed Secrets is the industry standard for single-cluster setups without an external secret store. It eliminates the imperative `apply-secrets` step.
- External Secrets Operator was rejected as overengineered — it requires an external store (Vault, AWS SM) that adds operational overhead for a single-node cluster.
- KSOPS was rejected due to fragile plugin management across kustomize versions and poor ArgoCD integration compared to Sealed Secrets.

## Consequences

- Prod deploy requires running `toolkit apply-secrets` before kustomize apply (documented in runbook)
- `secrets.yaml` removed from prod overlay to prevent placeholder deployment
- Staging keeps its current pattern (inline secrets in overlay) — acceptable for non-public staging
- When Phase 2 activates, SEAL-001..004 tasks cover the migration
