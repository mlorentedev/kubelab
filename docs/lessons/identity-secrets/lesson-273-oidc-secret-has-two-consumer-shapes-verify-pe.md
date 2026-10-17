---
id: lesson-273-oidc-secret-has-two-consumer-shapes-verify-pe
type: lesson
status: active
created: "2026-05-30"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# OIDC secret has two consumer shapes — verify per delivery mechanism, not uniformly

**Context:** Designing ADR-040 (OIDC client-secret lifecycle) and OIDC-DRIFT-001 (token round-trip verification in configure-oidc). The instinct was to treat "the consumer side" of the OIDC secret as one thing that DRIFT-001's token round-trip would cover.
**Problem:** The OIDC secret reaches consumers via THREE structurally different mechanisms (updated 2026-05-30 after Codex P2 on PR #233 — initial draft said two), and neither a single verifier nor a single propagation step covers all of them. (1) Gitea: pushed imperatively into SQLite via `gitea admin auth update-oauth` (propagate: `configure-oidc`; verify: DRIFT-001 token round-trip). (2) MinIO/Grafana: env var from a K8s Secret, Path 1 (propagate: `apply-secrets`+restart; verify: OIDC-E2E-001). (3) Argo CD: Helm `--set configs.secret.extra.oidc.authelia.clientSecret` via `make deploy-argocd`, sourced from COMMON SOPS not per-env (propagate: `deploy-argocd`; verify: OIDC-E2E-001). Grouping consumers by what they are NOT (e.g. "not admin-API → env-var") put Argo CD in the wrong bucket; group by PROPAGATION mechanism instead. Gitea: pushed imperatively into its SQLite OAuth source via `gitea admin auth update-oauth` — verifiable by configure-oidc's token round-trip. MinIO/Grafana/Argo CD: delivered declaratively as an env var from a K8s Secret (ADR-038 Path 1, e.g. MINIO_IDENTITY_OPENID_CLIENT_SECRET) — configure-oidc NEVER runs for them, so DRIFT-001 says nothing about them. Describing consumer verification as "shipped/covers all consumers" would let OIDC-SYNC-002 be built to "reuse DRIFT-001" while stale MinIO/Grafana/ArgoCD secrets pass silently — the exact drift the work was meant to kill. (Caught by Codex P2 on PR #232.)
**Solution:** Scope every verification claim to its delivery mechanism. admin-API consumer (Gitea) -> token round-trip (DRIFT-001, shipped #231). env-var consumers (MinIO/Grafana/ArgoCD) -> programmatic OIDC flow test per client (OIDC-E2E-001, still required — they are UNVERIFIED until it lands). Invariant: no OIDC operation reports success for a consumer it cannot actually verify; an unverifiable consumer is reported as a gap, never green. Recorded in ADR-040; OIDC-E2E-001 reclassified required (not optional); new ticket PROVIDER-GEN-001 (fold argon2 hash gen into Authelia config render, retire sync_oidc_hashes). General principle: when a value is delivered by N different mechanisms, it needs N propagation steps and the right verifier per mechanism — "the consumer side" is rarely one thing, and Codex needed two rounds (PR #232 two-shapes, PR #233 three-shapes) to fully tease the categories apart. Categorize by HOW the value propagates, never by what it is not.
**Tags:** `#oidc` `#authelia` `#adr` `#verification` `#secret-lifecycle` `#kubelab`
