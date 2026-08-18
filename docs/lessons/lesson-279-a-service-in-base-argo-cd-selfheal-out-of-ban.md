---
id: lesson-279-a-service-in-base-argo-cd-selfheal-out-of-ban
type: lesson
status: active
created: "2026-06-17"
owner: manu
tags: [kubelab, lesson, argocd, gitops, secrets, apply-secrets, k8s, authelia, notify-001, gotcha]
---

# A service in `base/` + Argo CD selfHeal + out-of-band Secrets = silent prod degradation

**Context:** PR #670 (notification fabric) squash-merged to master. The apprise Deployment lives in `infra/k8s/base/services/apprise.yaml` (so it deploys to ALL envs), but its `apprise-secrets` Secret was catalog-marked staging-only (`envs=("staging",)`). Argo CD prod runs `selfHeal: true` (ADR-037).
**Problem:** Argo CD auto-synced the apprise *manifest* to prod, but **Secrets are applied out-of-band** by the toolkit (`make apply-secrets`, which nobody ran for prod). The pod's initContainer hit `FailedMount: secret "apprise-secrets" not found` → stuck `Init:0/1` → Argo CD reported the app *Degraded*. (prod was never *down* — apprise is internal notify — but the board went red.) The same merge introduced a second latent break: #670 moved n8n `core`→`automation`, but `k8s_secrets.py` still mapped `APPS_SERVICES_CORE_N8N_ENCRYPTION_KEY` → `apply-secrets` skipped `n8n-secrets` and exited non-zero in *every* env. And the prod n8n IngressRoute applied the `authelia` middleware to the whole host, so the `/webhook/` ingress (n8n's own Header Auth) was 303-redirected to the Authelia login page — the fabric was unreachable end-to-end in prod, invisible because staging has no Authelia on n8n.
**Solution:** Two-surface rule for any new service added to `base/`: either (a) **gate it per-env** (move to the staging overlay) until deliberately promoted, OR (b) **ensure its Secret exists in every env it deploys to BEFORE the merge** (broaden the catalog `envs`, `secrets init`/`set`, run `apply-secrets`). When promoting a notify/webhook service to a prod host fronted by Authelia, add a higher-priority `Host(...) && PathPrefix(/webhook/)` route WITHOUT the authelia middleware (the app enforces its own auth there). General invariant: **manifests propagate via Argo CD, secrets via `apply-secrets` — nothing reconciles the two**, so a service can reach prod without its secret. Surfaced the need for catalog-driven secret application (ticket). Also: a catalog ref (`CORE` vs `AUTOMATION`) silently broke `apply-secrets` because runtime tests exercise the runtime path, not the catalog-apply path (recurring SSOT-catalog lesson). Shipped in PR #672.
**Tags:** `#argocd` `#gitops` `#secrets` `#apply-secrets` `#k8s` `#authelia` `#notify-001` `#gotcha`
