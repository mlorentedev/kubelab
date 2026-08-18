---
id: lesson-264-argo-cd-selfheal-breaks-test-before-merge-wor
type: lesson
status: active
created: "2026-05-23"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery]
---

# Argo CD selfHeal breaks "test-before-merge" workflow without explicit pause

> **Superseded by ADR-037 (2026-05-23, same day).** ARGO-015 / PR #211 institutionalized path (1) for staging (`selfHeal: false`) and kept path (2) as the only viable mode for prod (`selfHeal: true`). Solution section below is preserved for the prod-only case; staging no longer needs the patch dance.

**Context:** During AI-001 PR-C smoke, user wanted to test changes in prod BEFORE merging the PR — sensible test-before-merge discipline. Standard approach: deploy from feature branch worktree, smoke, then merge if good.
**Problem:** `kubelab-prod` Argo CD Application has `automated: {prune: true, selfHeal: true}`. Within seconds of `kubectl apply -k` from the feature worktree, Argo CD detected drift from master (which didn't yet have the change) and reverted the IngressRoute. The Middleware CRD `api-key-ollama` (NOT in git, lives only in `.rendered/` per ADR-035) survived because Argo doesn't manage it. Net effect: kubectl apply from feature branch is a no-op for git-tracked resources in this GitOps setup. "Test before merge" via kubectl is impossible without intervention.
**Solution:** Three viable paths for GitOps prod test-before-merge: (1) Temporarily disable `selfHeal` on the Application (`kubectl patch app kubelab-prod -p '...selfHeal:false'`), apply from feature worktree, smoke, re-enable. (2) Merge first, rely on Argo sync (~3min), smoke after. If broken, `git revert` + push triggers re-revert. (3) Trust local `kubectl kustomize` validation — for purely-declarative changes (manifest only, no migrations), the render output IS the cluster diff. We chose (2) for AI-001 PR-C — Argo synced within seconds of merge, smoke confirmed within minutes. For future high-risk changes, (1) is the safer pattern. Always know which mode you're in before testing in prod.
**Tags:** `#argocd` `#gitops` `#prod` `#workflow` `#ai-001`
