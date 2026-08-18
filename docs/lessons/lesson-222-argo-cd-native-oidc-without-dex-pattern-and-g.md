---
id: lesson-222-argo-cd-native-oidc-without-dex-pattern-and-g
type: lesson
status: active
created: "2026-03-27"
owner: manu
tags: [kubelab, lesson, argocd, oidc, authelia, helm, sso]
---

# Argo CD native OIDC without dex — pattern and gotchas

**Context:** Implementing ARGO-010: Argo CD SSO via Authelia OIDC on t4g.micro (1GB RAM)
**Problem:** Dex is disabled to save RAM on t4g.micro. Need OIDC without it. Also: hub credentials (OIDC secret) must live in common SOPS, not per-env. sync_oidc_hashes.py only read env-specific SOPS, missing common secrets. Deploy order matters: Authelia must have the OIDC client registered before Argo CD tries discovery.
**Solution:** Argo CD v2.5+ supports native OIDC via configs.cm.oidc.config (no dex). Secret referenced as $oidc.authelia.clientSecret from configs.secret.extra, injected at deploy time via Helm --set. sync_oidc_hashes.py now merges common SOPS as fallback. deploy-argocd Makefile target enforces order: _deploy-authelia-oidc → _deploy-argocd-helm. Admin local account restricted to apiKey only (CLI fallback). RBAC: admins group → role:admin, default readonly.
**Tags:** `#argocd` `#oidc` `#authelia` `#helm` `#sso`
