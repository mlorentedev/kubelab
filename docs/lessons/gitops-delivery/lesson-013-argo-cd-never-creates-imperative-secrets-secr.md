---
id: lesson-013-argo-cd-never-creates-imperative-secrets-secr
type: lesson
status: active
created: "2026-06-20"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, gitops, secrets, sops, toolkit, adr-037, issue-723, issue-724]
---

# Argo CD never creates imperative Secrets — "secret not found" after sync is expected

**Context**: After merging the Postgres manifest (#720), Argo CD reported the Postgres app **Degraded**: `secret "postgres-secrets" not found`.

**Problem**: K8s Secrets in this repo are not in git — the overlay `secrets.yaml` carries only `REPLACE_WITH_SOPS_VALUE` placeholders. Real values are applied imperatively at deploy time via `toolkit secrets apply` (SOPS → rendered Secret → `kubectl apply`). Argo CD syncs only what is committed, so it never creates these Secrets; a freshly-synced workload that consumes one is *expected* to report Degraded until the apply step runs. Here the apply was deferred (no kubeconfig reachable from the workstation — the single `~/.kube/kubelab.config` points at a LAN IP, `172.16.1.10`, unreachable over Tailscale), tracked as #723 (build `make fetch-kubeconfig ENV=staging|prod`) → #724 (apply the secrets).

**Solution**: None needed on the manifest — the Degraded state is the secret-apply step pending, not a defect. Ticketed #723/#724 so the apply is not lost.

**Rule**: In a GitOps repo where Secrets are applied imperatively (not committed), `secret not found` immediately after a sync is expected, not a regression — the secret-apply is a separate, out-of-band action. Track it as a follow-up and don't debug the manifest. Corollary: provisioning a secret in SOPS and applying it to the cluster are two distinct steps; merging the manifest performs neither.

**Tags**: `#argocd` `#gitops` `#secrets` `#sops` `#toolkit` `#adr-037` `#issue-723` `#issue-724`
