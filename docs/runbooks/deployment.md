---
id: "kubelab-runbook-deployment"
type: runbook
status: superseded
superseded_by: gitops-delivery-promotion
tags: [runbook, kubelab]
created: "2026-02-08"
updated: "2026-07-07"
owner: manu
---

# Deployment (retired)

> **This runbook described the pre-K3s world** — Docker Compose production, a Gitflow
> `develop` branch, and a `make deploy-prod` target that no longer exists. It was retired
> by the 2026-07-07 docs audit (finding D7, `docs/audits/docs-audit-2026-07-07.md`).

The canonical deployment / promotion / rollback reference is
**[gitops-delivery-promotion.md](gitops-delivery-promotion.md)**:

- **Staging**: `staging-deploy.yml` promotes `sha-<short>` images via a
  `chore(staging): deploy` PR; Argo CD staging app syncs with `selfHeal: false` (ADR-037).
- **Production**: release-please cuts per-app semver tags and re-tags the staging sha
  digest (build-once, ADR-056); the `promote-prod.yml` workflow is the manual gate;
  Argo CD prod app syncs with `selfHeal: true`.
- **Rollback**: revert the promotion PR so Argo CD reconciles — never
  `git checkout <tag>` + redeploy.

Related: [pre-prod-verification.md](pre-prod-verification.md) ·
[k3s-setup.md](k3s-setup.md) · `make deploy-k8s ENV=<env>` for direct staging pushes.
