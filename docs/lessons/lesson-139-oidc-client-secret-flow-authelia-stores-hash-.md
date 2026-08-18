---
id: lesson-139-oidc-client-secret-flow-authelia-stores-hash-
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, oidc, authelia, secrets, sops]
---

# OIDC client_secret flow: Authelia stores hash, client stores plaintext

**Context:** Configuring OIDC SSO between Authelia (IdP) and Gitea/Grafana (clients) on K3s.

**Problem:** Confused which side stores hash vs plaintext. Authelia docs show argon2 hash in configuration, but it wasn't clear the client service needs the raw plaintext secret (like a password).

**Solution:** Same as password hashing: Authelia stores the argon2 HASH in its ConfigMap. The client service (Gitea, Grafana) stores the PLAINTEXT in its env/config (from K8s Secret). `toolkit secrets hash` auto-generates missing OIDC client secrets and stores plaintext in SOPS, hash in Authelia config.

**Rule:** OIDC client_secret = password pattern. Hash in IdP config, plaintext in client config (sourced from SOPS). Never put plaintext in ConfigMaps.
**Tags:** `#oidc` `#authelia` `#secrets` `#sops`
