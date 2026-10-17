---
id: lesson-082-e2e-audit-gitea-staging-uses-prod-domain-no-o
type: lesson
status: active
created: "2026-02-28"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# E2E Audit: Gitea Staging Uses Prod Domain (No Override)

**Context**: E2E test suite expansion — cross-checking service domains across environments.

**Problem**: `infra/config/values/staging.yaml` has no domain override for Gitea. The base config (`common.yaml`) uses the production domain `gitea.kubelab.live`. In staging, Gitea is accessible at `gitea.staging.kubelab.live` via Traefik IngressRoute, but the config-generated domain doesn't match. Tests targeting the Gitea domain from the merged config would hit the wrong environment.

**Solution**: Add `domain: gitea.staging.kubelab.live` to the Gitea section in `staging.yaml`.

**Rule**: Every service deployed in staging must have an explicit domain override in `staging.yaml`. Never rely on the base config domain for non-prod environments — it defaults to prod.

---
