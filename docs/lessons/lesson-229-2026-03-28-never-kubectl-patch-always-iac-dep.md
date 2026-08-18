---
id: lesson-229-2026-03-28-never-kubectl-patch-always-iac-dep
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-28: Never kubectl patch — always IaC (deploy-argocd, deploy-k8s, deploy TARGET=vps)

**Symptom:** ArgoCD RBAC policy.csv was empty in cluster despite being defined in Helm values. OIDC users could authenticate but saw no Applications.

**Root cause:** `make deploy-argocd` Helm upgrade failed or timed out on t4g.micro (OOM). The RBAC values in `infra/helm/argocd/values.yaml` were never applied. The quick-fix instinct was to `kubectl patch` — WRONG.

**Rule:** NEVER apply changes directly to the cluster via kubectl patch/apply for resources managed by Helm or Kustomize. Always use the IaC pipeline:
- ArgoCD config → `make deploy-argocd` (Helm upgrade)
- K8s workloads → `make deploy-k8s ENV=x` (Kustomize apply)
- VPS services → `make deploy TARGET=vps ENV=prod` (Ansible)
- DNS/Cloudflare → `make tf-dns-apply` (Terraform)

**Why:** Manual patches create drift. Helm doesn't know about them → next `helm upgrade` may revert or conflict. ArgoCD with selfHeal will revert manual changes. The whole point of IaC is that the cluster state matches Git.

**Fix pattern:** If a Helm value isn't applied, diagnose WHY the deploy failed (OOM, timeout, values error) and re-run the deploy — don't bypass it.

**Affected services to audit:** Any Helm-managed resource where values may not have been applied due to aws1 OOM:
- ArgoCD RBAC (confirmed missing)
- ArgoCD OIDC client secret (may need re-injection via `--set`)
- Any Helm chart on aws1 hub
