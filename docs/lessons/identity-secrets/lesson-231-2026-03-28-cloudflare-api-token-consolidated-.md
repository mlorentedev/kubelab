---
id: lesson-231-2026-03-28-cloudflare-api-token-consolidated-
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# 2026-03-28: Cloudflare API token consolidated — old "DNS mlorente.dev" revoked

**Action:** Replaced narrow-scope "DNS mlorente.dev" token (Zone:DNS:Edit + Zone:Read) with "kubelab-terraform" token (DNS:Edit + Zone:Read + Zone Settings:Edit). Old token revoked. New token stored in SOPS `cloudflare.api_token` (common.enc.yaml). Covers all Terraform operations (DNS records, zone settings, CAA records).
