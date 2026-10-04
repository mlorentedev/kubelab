---
id: lesson-513-a-cloudflare-account-token-is-verified-against-the-account-not-the-user
type: lesson
status: active
created: "2026-10-03"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, cloudflare, r2, backup]
---

# A Cloudflare account token is verified against the account, not the user, and only a token that can edit tokens can mint one

**Context**: BACKUP-057 mints one R2 token per backup node through the Cloudflare API (`toolkit backup mint-node-tokens`). The repository already watched Cloudflare token expiry through `GET /user/tokens/verify`.

**Problem**: Two calls failed that looked like they should work.

- `cloudflare.r2_admin_token` holds *Workers R2 Storage: Edit*. It got **HTTP 403** on `GET /accounts/{id}/tokens/permission_groups`. Creating a token, or even listing the permission groups a token could be given, needs *Account API Tokens: Edit*. No R2 permission includes it.
- The dedicated minter is an **account** token, created under Manage Account > Account API Tokens. It got **HTTP 401** on `/user/tokens/verify`, the endpoint the expiry check used for every Cloudflare token. A 401 reads as "revoked". The token was active: `/accounts/{id}/tokens/verify` answered `status: active` with its `expires_on`.

**Solution**: Minting goes through a token of its own, `cloudflare.r2_token_minter`, with *Account API Tokens: Edit* and a TTL. Its expiry is read by `cloudflare_account_token_expiry`, which asks `/accounts/{account_id}/tokens/verify` and takes the account id from `backup.r2.account_id`. It is registered in `PROVIDER_CHECKS` next to the user-token checker.

**Rule**: Before wiring a Cloudflare token into anything, ask which kind it is.

- A user token is verified at `/user/tokens/verify`. An account token is verified at `/accounts/{id}/tokens/verify`, and the user endpoint answers 401 for it.
- Creating tokens is its own permission, and it can grant anything. Keep it in a dedicated token with an expiry; never fold it into a working token.

**Tags**: `#cloudflare` `#r2` `#BACKUP-057` `#pr-2050`
