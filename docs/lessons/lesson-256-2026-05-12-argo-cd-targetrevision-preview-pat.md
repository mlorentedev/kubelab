---
id: lesson-256-2026-05-12-argo-cd-targetrevision-preview-pat
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-05-12 — Argo CD `targetRevision` preview pattern for visual PR validation

> **Superseded for staging by ADR-037 (2026-05-23).** Staging now runs with `selfHeal: false` (ARGO-015 / PR #211), so `make deploy-k8s ENV=staging` from a feature worktree is again the natural test-before-merge path — no targetRevision repointing needed. The technique below remains useful for **prod** (where `selfHeal: true` is preserved by design) and for any future Application with auto-sync; keep this lesson for that narrower use case.

**Problem.** Staging on Argo CD GitOps (auto-sync + selfHeal) reverts any `kubectl apply` that doesn't match the configured `targetRevision` (master). The old loop "feature branch → `make deploy-k8s ENV=staging` → validate → PR" is dead. Trunk-based rule + visual-test-before-merge requirement become mutually exclusive without a preview mechanism.

**Discovered during** PR1 dashboard cosmetic (`fix/dash-ui-cosmetic`, PR #171, 2026-05-12). `make deploy-k8s ENV=staging` apparent-succeeded but the pod still served stale `custom.js` (footer date 2026-03-28 instead of 2026-05-12). Diagnosed via the `argocd.argoproj.io/tracking-id` annotation on the homepage Deployment plus comparing local `kubectl kustomize` ConfigMap name hash vs the deployed Deployment's `volumes.configMap.name`.

**Solution.** Temporarily point Argo at the feature branch:

```bash
# After commit + push of feature branch to GitHub:
kubectl --kubeconfig ~/.kube/kubelab-hub-config -n argocd patch application kubelab-staging \
  --type merge -p '{"spec":{"source":{"targetRevision":"fix/branch-name"}}}'

# Force immediate refresh (don't wait ~3min polling):
kubectl --kubeconfig ~/.kube/kubelab-hub-config -n argocd annotate application kubelab-staging \
  argocd.argoproj.io/refresh=hard --overwrite

# Validate in browser. Hard refresh (Ctrl+Shift+R) to bypass client cache.

# After merge PR to master, patch back:
kubectl --kubeconfig ~/.kube/kubelab-hub-config -n argocd patch application kubelab-staging \
  --type merge -p '{"spec":{"source":{"targetRevision":"master"}}}'
```

**Limitations.**

- One feature branch at a time per Application (staging mirrors one branch).
- Forgetting the patch-back leaves staging anchored to a deleted branch → no further master updates land. MUST track in MEMORY.md handoff + harness task.
- Browser cache: ConfigMap hash suffix changes the K8s ConfigMap NAME, NOT the URL served to the browser. `custom.js`/`custom.css` URLs are stable — hard refresh required for visual validation.
- `selfHeal: true` stays ON during preview: any ad-hoc `kubectl edit` during the test is reverted to the branch state. Good for clean tests, bad for ad-hoc patches.

**Future automation candidates.**

- ApplicationSet with PR generator for automatic per-PR ephemeral preview environments (multi-PR support).
- Argo CD Notifications + webhook to auto-revert `targetRevision` when the PR merges.
- Makefile wrappers: `make argo-preview APP=… REV=…` and `make argo-revert APP=…` to encapsulate the patches.

**When NOT to use.**

- Prod: changing `targetRevision` on prod would be a security incident.
- PRs touching non-K8s state (Ansible, Terraform): no Argo to redirect — use the regular apply workflow.
- PRs that fully validate locally and have no visual/UI component: trust kustomize, skip the preview ceremony.
