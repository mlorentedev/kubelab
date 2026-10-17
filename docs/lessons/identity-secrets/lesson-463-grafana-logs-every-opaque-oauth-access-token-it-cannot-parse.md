---
id: lesson-463-grafana-logs-every-opaque-oauth-access-token-it-cannot-parse
type: lesson
status: active
created: "2026-09-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, grafana, oidc, authelia, loki, sec-021]
---

# Grafana logs every opaque OAuth access token it cannot parse, so each SSO login wrote a live bearer token to Loki

**Context**: Validating the removal of Grafana's email-lookup migration flag in staging, a Loki read of Grafana's `warn` lines printed a `testuser` access token into an agent transcript.

**Problem**: Grafana 13.0.2 reads user info from three sources on every generic OAuth login: the ID token, UserInfo, and the access token. The access-token source is not configurable (`collectUserInfoData`, `generic_oauth.go:263`). It parses the token as a JWT, and on failure `retrieveRawJWTPayload` returns `token is not in JWT format: %s` with the token inside, which `extractFromAccessToken` logs at `warn`. Authelia issues opaque access tokens by default, so every login took that path. Measured on 2026-09-26: 3 tokens in prod Loki, two of them Admin, and 19 in staging, from the day OIDC became Grafana's only login (#1825). Vikunja and Authelia were logging authorization codes too.

**Solution**: SEC-021 (#1840). The `grafana` client declares `access_token_signed_response_alg: RS256`, so Authelia issues an RFC 9068 JWT and Grafana parses it instead of logging it. Grafana keeps the first value per field, so the role still comes from UserInfo. Vector redacts `authelia_(at|rt|ac)_` values before Loki for every container. The stored lines were left to retention, because every one was already expired or consumed.

**Rule**: A log line that quotes the input it failed to parse leaks that input. When an app consumes credentials, check what it logs on the unhappy path of each credential it receives, not just on the happy one. Read Loki around auth through a local redactor, and count before you read.

**Tags**: `#grafana` `#oidc` `#sec-021`
