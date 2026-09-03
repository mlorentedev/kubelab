# Argo CD, releases and image promotion

27 lessons, newest first. Back to [all categories](../_index.md).

| # | Lesson | Date |
|---|---|---|
| 417 | [An IaC module that was never applied is read as a control, and the header saying otherwise does not stop it](lesson-417-an-unapplied-iac-module-is-read-as-a-control.md) | 2026-09-02 |
| 407 | [A failed Argo CD auto-sync is not retried, and a merged manifest is not a deploy](lesson-407-a-failed-auto-sync-is-not-retried-and-a-merge-is-not-a-deploy.md) | 2026-08-27 |
| 404 | [A ConfigMap of env vars without a hash suffix is a silent no-op, and Argo CD reports Synced](lesson-404-a-configmap-of-env-vars-without-a-hash-suffix-is-a-silent-no-op.md) | 2026-08-26 |
| 377 | [Under selfHeal, a rotation that is not committed is a scheduled outage](lesson-377-rotating-is-not-landing-under-selfheal.md) | 2026-08-23 |
| 375 | [A comment claiming another target does it is not a chain](lesson-375-a-comment-claiming-another-target-does-it-is-not-a-chain.md) | 2026-08-23 |
| 368 | ["Closed in code" is not closed, and the gap is invisible until something runs](lesson-368-a-finding-closed-in-code-was-never-executed.md) | 2026-08-22 |
| 372 | [`Synced`/`Healthy` with an empty history had never written](lesson-372-synced-and-healthy-with-an-empty-history-had-never-written.md) | 2026-08-23 |
| 362 | [Designing a guard for a future hazard found it already loaded and aimed at prod](lesson-362-designing-a-guard-for-a-future-hazard-found.md) | 2026-08-21 |
| 333 | [One placeholder document exiled a whole manifest from GitOps, and `Synced` said nothing](lesson-333-one-placeholder-document-exiled-a-whole-manif.md) | 2026-08-15 |
| 330 | [Staging's `selfHeal: false` doesn't stop Argo CD from reverting a manual deploy mid-session — it only suppresses drift correction, not new-revision sync](lesson-330-staging-s-selfheal-false-doesn-t-stop-argo-cd.md) | 2026-08-15 |
| 331 | [A local `kubectl diff` against an Argo CD-managed cluster describes a merge that will never happen](lesson-331-a-local-kubectl-diff-against-an-argo-cd-manag.md) | 2026-08-15 |
| 319 | [A manifest changed in git is a claim, not a deployed fact — nothing was reading back the live Argo CD Application](lesson-319-a-manifest-changed-in-git-is-a-claim-not-a-de.md) | 2026-08-12 |
| 314 | [`bootstrap-sha` in `release-please-config.json` is a manifest-level option, not a per-package one](lesson-314-bootstrap-sha-in-release-please-config-json-i.md) | 2026-08-12 |
| 286 | [Build-once re-tag (ADR-056): read the raw staging pin, protect it from the prune, copy the manifest list](lesson-286-build-once-re-tag-adr-056-read-the-raw-stagin.md) | 2026-06-27 |
| 287 | [Pick the SSOT lane by where the version lives, not by "it's a custom app" (DELIVERY-003)](lesson-287-pick-the-ssot-lane-by-where-the-version-lives.md) | 2026-06-27 |
| 013 | [Argo CD never creates imperative Secrets — "secret not found" after sync is expected](lesson-013-argo-cd-never-creates-imperative-secrets-secr.md) | 2026-06-20 |
| 279 | [A service in `base/` + Argo CD selfHeal + out-of-band Secrets = silent prod degradation](lesson-279-a-service-in-base-argo-cd-selfheal-out-of-ban.md) | 2026-06-17 |
| 264 | [Argo CD selfHeal breaks "test-before-merge" workflow without explicit pause](lesson-264-argo-cd-selfheal-breaks-test-before-merge-wor.md) | 2026-05-23 |
| 026 | [Argo CD hub OOM cascade on aws1 (t4g.small Spot)](lesson-026-argo-cd-hub-oom-cascade-on-aws1-t4g-small-spo.md) | 2026-05-06 |
| 236 | [2026-03-29: ArgoCD notifications — service.webhook not service.slack for incoming webhooks](lesson-236-2026-03-29-argocd-notifications-service-webho.md) | 2026-05-01 |
| 122 | [2026-03-16: CI/CD and Branching Simplification](lesson-122-2026-03-16-ci-cd-and-branching-simplification.md) | 2026-05-01 |
| 240 | [2026-03-29: ArgoCD selfHeal reverts manual kubectl apply instantly](lesson-240-2026-03-29-argocd-selfheal-reverts-manual-kub.md) | 2026-05-01 |
| 256 | [2026-05-12 — Argo CD `targetRevision` preview pattern for visual PR validation](lesson-256-2026-05-12-argo-cd-targetrevision-preview-pat.md) | 2026-05-01 |
| 181 | [Argo CD spoke registration: scoped RBAC > cluster-admin](lesson-181-argo-cd-spoke-registration-scoped-rbac-cluste.md) | 2026-03-23 |
| 185 | [Argo CD resource.exclusions selector may not work](lesson-185-argo-cd-resource-exclusions-selector-may-not-.md) | 2026-03-23 |
| 183 | [Hub↔spoke traffic should use VPN, not public IPs](lesson-183-hub-spoke-traffic-should-use-vpn-not-public-i.md) | 2026-03-23 |
| 176 | [release-please only bumps on fix:/feat: commits — chore: is ignored](lesson-176-release-please-only-bumps-on-fix-feat-commits.md) | 2026-03-22 |
