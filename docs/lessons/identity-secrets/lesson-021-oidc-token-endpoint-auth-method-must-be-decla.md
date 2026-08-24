---
id: lesson-021-oidc-token-endpoint-auth-method-must-be-decla
type: lesson
status: active
created: "2026-05-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, authelia, oidc, gotcha, version-defaults, pr-227]
---

# OIDC `token_endpoint_auth_method` must be declared explicitly on every client

**Context**: Discovered during manual OIDC smoke after PR #225/#226/#227. Browser flow `gitea.kubelab.live → Sign in via Authelia` returned `invalid_client` with the message: *"The request was determined to be using 'token_endpoint_auth_method' method 'client_secret_post', however the OAuth 2.0 client registration does not allow this method."* Root cause: Authelia 4.39.x defaults the per-client `token_endpoint_auth_method` to `client_secret_basic` when the field is absent, but Gitea 1.25.x sends credentials in the POST body (`client_secret_post`). The server rejected the token request. Pre-existing bug, latent for at least one release cycle — no automated test exercises the interactive OIDC code flow (the existing `auth_flow.py` only exercises ForwardAuth via cookie sessions, never the `/token` endpoint).

**Problem**: OIDC client registrations rely on implicit defaults that differ between (a) the identity provider's version, (b) the relying party's version, and (c) the OAuth 2.0 spec's "default to whatever". Authelia and Gitea picked different defaults; the mismatch only manifests at the token exchange step, which automated ForwardAuth tests never reach. Worse, the same shape applies to other fields with version-dependent defaults: `id_token_signed_response_alg`, `userinfo_signed_response_alg`, `response_types`. Any of them could break silently in a future bump.

**Solution**: PR #227 declared `token_endpoint_auth_method` explicitly on all 4 clients in both staging and prod `configuration.yml`: `gitea → client_secret_post` (the fix), `minio | grafana | argocd → client_secret_basic` (the current implicit default, declared explicitly so a future Authelia upgrade that changes the default cannot silently break them too). Inline comment on the gitea client documents why it differs.

**Rule**: For any OIDC client registration, declare every field whose default has differed historically across versions of the IdP — even when the implicit default works today. The cost is 3-5 lines per client; the value is that a version bump (Authelia 4.39 → 4.40 → 5.x) cannot silently break the integration. Generalizes to any client/server protocol with negotiable defaults: HTTP/2 settings, TLS cipher suites, JWT algorithms. The principle is "declare your intent, do not rely on implicit defaults". Pairs with OIDC-E2E-001 (programmatic code-flow tests) which catches the runtime failure even when the declaration is missing.

**Addendum (2026-08-23, #1357)**: the Solution above describes #227's *intent*, and #227 did not deliver it. `gitea` and `argocd` were registered with each other's values — gitea got `client_secret_basic`, argocd got `client_secret_post` — and they carried the swap from May until August without anyone noticing, because the inline comment on the gitea client asserted it sends POST while the value beneath it said basic. **The comment was part of the defect**: it described the correct intent, so every subsequent reader validated the value against the comment instead of against the client. Fixed in #1357 for the prod overlay *and* the base that serves staging. Diagnostic, which needs no inference: Authelia's rejection names both the method it detected and the method the registration allows, so `kubectl logs deploy/authelia -n kubelab | grep invalid_client` identifies any future mismatch and says which side is wrong. See also [lesson-020](lesson-020-comment-vs-implementation-drift-pair-auto-fil.md) for the general comment-drift shape.

**Tags**: `#authelia` `#oidc` `#gotcha` `#version-defaults` `#pr-227` `#pr-1357`
