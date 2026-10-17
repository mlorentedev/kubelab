---
id: lesson-217-sec-004-sops-multi-recipient-for-ci-adr-027-p
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# SEC-004: SOPS Multi-Recipient for CI (ADR-027 Phase 2, 2026-03-27)

**What:** Added a dedicated CI AGE key as second SOPS recipient. All 4 `.enc.yaml` files re-encrypted with `sops updatekeys`. CI private key stored as GitHub Actions secret `SOPS_AGE_KEY`. Human key stays on VeraCrypt USB.

**Why:** `toolkit sync oidc --check` needs to decrypt SOPS to validate OIDC hash drift. Without a CI key, this check is skipped in pipelines — drift goes undetected.

**How to reproduce:** See ADR-027 in vault for full setup steps. Keys: human = `age166v8e...`, CI = `age1wpqxa...`. Both public keys in `.sops.yaml`.

**Rotation:** Generate new CI key → update `.sops.yaml` → `sops updatekeys` on all files → update GitHub secret. Human key unaffected.
