---
id: lesson-319-a-manifest-changed-in-git-is-a-claim-not-a-de
type: lesson
status: active
created: "2026-08-12"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery]
---

# A manifest changed in git is a claim, not a deployed fact — nothing was reading back the live Argo CD Application

**Context:** Verifying OPS-022 (#969) in staging, `make deploy-k8s ENV=staging` applied the Pi-hole overlay move correctly — then the live IngressRoute reverted to its old `Host()` 19 seconds later, with no action taken in between.

**Problem:** The live `kubelab-staging` Argo CD Application had `selfHeal: true`, even though git (`infra/k8s/argocd/applications/staging.yaml`) has said `selfHeal: false` since PR #211 (ARGO-015/ADR-037, merged 2026-05-24) — the whole point of that PR being that staging needed to tolerate a direct `make deploy-k8s` without Argo CD reverting it within seconds. `kubectl diff -f infra/k8s/argocd/applications/ --kubeconfig ~/.kube/kubelab-hub-config` confirmed this was the *only* delta — prod's live object matched its git file exactly, so this wasn't a deliberate override drifting elsewhere too. `managedFields` on the live object showed why: its last full `kubectl apply` was 2026-03-29, *before* PR #211 existed, and a `kubectl-patch` on 2026-05-19 never touched `syncPolicy`. Nobody ran `make deploy-apps` after PR #211 merged, and nothing checked that the live object had actually changed — the same defect shape as the yamllint header overstating CI coverage and the `overlays/prod/patches.yaml` `tls: {}` comment claiming a resolver was gone (both earlier entries in this file): a comment, a merged PR, or a config file all *describe an intent*, and none of them are the same fact as "the live object matches."

**Solution:** Structural fix in PR #1020 — `toolkit infra argo check-drift` runs `kubectl diff` against the Applications directory and treats its exit code as three-way, not two: clean, drift-found, or *hub unreachable* (the last one found live, for free, because aws1 happened to be down for an unrelated Spot-reclaim reason during this exact investigation — measured kubectl's own default timeout there at ~60s, bounded to ~30s with `--request-timeout=15s`). Wired into `check-apps` for visibility and as a post-apply read-back inside `deploy-apps` itself, so the fix step verifies its own result instead of trusting `kubectl apply`'s exit code. The actual live fix (`make deploy-apps`) is a one-line no-op-on-git-side operation, but it was still blocked on the hub being reachable — the drift persisted for the rest of this session for exactly that reason.

**Rule:**
- **A `make <target>` that exists is not evidence it was ever run.** PR #211 shipped both the git change and the target that applies it, and still went undeployed for ~3 months — the review gate that would have caught it (`make deploy-apps` in the PR's own "how to verify" section) was never itself made mandatory or automated.
- **"Hub unreachable" must be a third state, never silently folded into "clean."** Collapsing "couldn't check" into "no drift found" is the exact mechanism that let this go unnoticed — any read-back check with only two possible answers (clean/dirty) will eventually make that mistake the first time its target goes offline.
- **The fastest way to prove staleness in a live object is a fresh, targeted `kubectl diff` against its exact git manifest — not a memory of when it was supposed to have changed.** `managedFields` timestamps were the tie-breaker between "deliberately overridden" and "simply never redeployed"; without them this would have needed a guess.

**Tags:** `#argocd` `#gitops` `#drift-detection` `#adr-037` `#silent-failure` `#ops-020` `#gotcha`
