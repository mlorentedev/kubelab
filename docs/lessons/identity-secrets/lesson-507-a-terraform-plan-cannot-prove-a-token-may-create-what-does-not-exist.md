---
id: lesson-507-a-terraform-plan-cannot-prove-a-token-may-create-what-does-not-exist
type: lesson
status: active
created: "2026-10-02"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, terraform, cloudflare, r2, backup]
---

# A `terraform plan` cannot prove a token may create something that does not exist yet

**Context**: BACKUP-057 PR 2 added an R2 Terraform root (one bucket and lock rule per node). Its Makefile targets first read the SOPS `cloudflare.api_token`, the token that already manages DNS, on the assumption that a Cloudflare account token would also reach R2.

**Problem**: `make tf-r2-plan` was clean with that token. `make tf-r2-apply SCRATCH=1` was refused on its first call: `POST /accounts/<id>/r2/buckets` returned **403**, code 10000 "Authentication error". Planning a resource that is not in state makes no API call for it. The provider only refreshes what already exists, so a plan of pure creates authenticates nothing beyond the provider's own setup, and a token without the permission plans exactly like one with it.

**Solution**: The operator minted a separate user API token (`Account · Workers R2 Storage · Edit`, this account only), stored as `cloudflare.r2_admin_token` and registered in `SECRET_CATALOG` with an expiry checker. `tf-r2-plan`/`tf-r2-apply` read only that key. The same scratch apply then created the bucket and its four-rule lock, rc 0. Keeping it separate also means the token that can lift a lock never reaches the DNS and ACME paths that only need DNS.

**Rule**: Verify a credential's permission by the operation that needs it, on something cheap and disposable (here a scratch bucket with a one-day lock), never by a plan. A clean plan says the configuration is valid and the provider can start. It says nothing about whether the token may create anything new. When a new root reuses an existing token, measure before writing the docs that assume it.

**Tags**: `#terraform` `#cloudflare` `#r2` `#backup-057` `#pr-1959`
