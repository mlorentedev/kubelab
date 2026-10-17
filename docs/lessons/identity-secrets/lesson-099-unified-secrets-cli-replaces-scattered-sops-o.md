---
id: lesson-099-unified-secrets-cli-replaces-scattered-sops-o
type: lesson
status: active
created: "2026-03-01"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Unified Secrets CLI Replaces Scattered sops/openssl Commands

**Context**: Multiple Makefile targets used raw `sops --set`, `openssl rand`, `sops --edit` with different patterns. No single entry point for secret operations.

**Problem**: Inconsistent secret management. Some targets used `sops --set` (broke with special chars), others used interactive `sops --edit`, and generation used various `openssl` invocations. No catalog of what secrets exist, no audit capability, no standard rotation procedure.

**Solution**: Created `toolkit secrets` CLI with 8 unified commands: `edit`, `init`, `jwks`, `hash`, `apply`, `audit`, `show`, `catalog`. All secret metadata centralized in `SECRET_CATALOG` (25 entries) in `toolkit/features/secrets_manager.py`. Makefile reduced to 5 thin wrappers. Comprehensive documentation in vault `40-runbooks/secrets-reference.md`.

**Rule**: Secret operations MUST go through `toolkit secrets *`. Never use raw `sops` or `openssl` in Makefile or scripts. The `SECRET_CATALOG` is the authoritative registry — every new secret must be registered there with its kind, services, and rotation notes.

---
