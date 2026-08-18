---
id: lesson-126-k8s-secrets-bootstrap-vs-application-lifecycl
type: lesson
status: active
created: "2026-03-17"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# K8s secrets: bootstrap vs application lifecycle

**Context:** ADR-023 Phase 1 provisioning review — discovered Cloudflare API token K8s Secret was missing from Ansible provisioning
**Problem:** Traefik HelmChartConfig referenced `cloudflare-api-token` Secret via secretKeyRef (no `optional: true`), but no Ansible task created it. Traefik would CrashLoopBackOff until secret was manually created. The question was: should this go through the existing `toolkit apply-secrets` pipeline or through Ansible?
**Solution:** Two secret categories with different lifecycles: (1) Bootstrap secrets — needed before pods start, deployed via Ansible templates to `/var/lib/rancher/k3s/server/manifests/` (same pattern as HelmChartConfig). Only 1 in the project: `cloudflare-api-token`. (2) Application secrets — 8 secrets, 23 keys, deployed via `toolkit apply-secrets` after K3s is running. K3s manifests dir is declarative, idempotent, and avoids chicken-and-egg. Future: Sealed Secrets (SEAL-001..004) replaces both mechanisms.
**Tags:** `#k8s` `#secrets` `#ansible` `#k3s` `#architecture`
