---
id: "adr-016"
type: adr
status: active
tags: [auth, oidc, authelia, minio, gitea, n8n]
owner: manu
created: "2026-03-28"
---

# ADR-016: OIDC Centralized Authentication via Authelia

## Status

Accepted 2026-02-28

## Context

KubeLab hosts multiple services (Gitea, N8N, MinIO, Grafana) each capable of managing their own authentication independently. This creates several problems:

- **Inconsistent UX**: Users must manage separate credentials per service, with different password policies and login flows.
- **Security fragmentation**: Each service has its own auth surface area, increasing the attack vector and making audit difficult.
- **Operational burden**: Adding a new service requires configuring yet another auth system, managing more credentials, and documenting another login flow.
- **No SSO**: Users authenticate repeatedly when navigating between services.

Authelia is already deployed as the authentication gateway for KubeLab (forward-auth via Traefik). It supports OIDC provider functionality, enabling native OIDC integration for services that support it.

## Decision

Use **Authelia as the central OIDC identity provider** for all KubeLab services. Services are classified into three authentication tiers based on their capabilities:

### Tier 1: OIDC (Native Integration)

Services with native OIDC/OAuth2 support bypass Authelia forward-auth and use Authelia as their OIDC provider directly. Users authenticate once via the Authelia OIDC login flow.

**Services**: MinIO, Gitea

- **MinIO**: Configured via environment variables (`MINIO_IDENTITY_OPENID_*`). Native OIDC support maps Authelia groups to MinIO policies.
- **Gitea**: Configured via post-deploy admin CLI (`gitea admin auth add-oauth`). Supports auto-discovery via `.well-known/openid-configuration`.

### Tier 2: Forward Auth

Services without OIDC support use Authelia forward-auth middleware at the Traefik reverse proxy layer. Authelia challenges unauthenticated requests before they reach the service.

**Services**: N8N, Grafana

- **N8N**: Community edition has no OIDC support. Forward-auth with `one_factor` policy provides authentication without requiring N8N configuration changes.
- **Grafana**: While Grafana supports OAuth2, using forward-auth simplifies the setup and keeps auth consistent with the Authelia session.

### Tier 3: Bypass

Truly public endpoints bypass authentication entirely. These are user-facing services that must be accessible without login.

**Services**: API, blog, landing page (web)

## Implementation Details

### OIDC Client Configuration

Each OIDC-enabled service requires a client registration in Authelia's configuration:

- **Client ID**: Service-specific identifier (e.g., `minio`, `gitea`)
- **Client Secret**: Stored in two forms:
  - **Plaintext**: In SOPS secrets, injected into the service's environment at deploy time
  - **Argon2 hash**: In Authelia's `identity_providers.oidc.clients[].secret` configuration
- **Redirect URIs**: Service-specific callback URLs (environment-dependent, patched via Kustomize overlays)
- **Scopes**: `openid profile email groups` (standard set for all clients)

### JWKS Key Management

- RSA 4096-bit key pair required per environment
- Private key stored in SOPS (`apps.services.security.authelia.oidc_jwks_rsa_private_key`)
- Mounted as a K8s Secret and referenced by Authelia's OIDC configuration
- Generated via `make secrets-jwks ENV=<environment>`

### Authelia Access Control

```yaml
access_control:
  default_policy: deny
  rules:
    # Tier 3: Public bypass
    - domain: ['api.*.kubelab.live', 'web.*.kubelab.live', '*.mlorente.dev']
      policy: bypass
    # Tier 1: OIDC services bypass forward-auth (auth handled by OIDC flow)
    - domain: ['minio.*.kubelab.live', 'gitea.*.kubelab.live']
      policy: bypass
    # Tier 2: Forward-auth services
    - domain: ['n8n.*.kubelab.live', 'grafana.*.kubelab.live']
      policy: one_factor
```

### Middleware Chain

All IngressRoutes follow the standard middleware chain:

- **OIDC services (Tier 1)**: `[secure-headers, error-pages, crowdsec-bouncer]` (no authelia middleware)
- **Forward-auth services (Tier 2)**: `[secure-headers, error-pages, crowdsec-bouncer, authelia]`
- **Public services (Tier 3)**: `[secure-headers, error-pages, crowdsec-bouncer]`

## Consequences

### Positive

- **Single identity provider**: All services authenticate through Authelia, providing a unified login experience.
- **SSO for OIDC services**: Users logging into MinIO or Gitea share the Authelia session, reducing authentication friction.
- **Centralized user management**: User accounts, groups, and policies managed in one place (Authelia's user database or future LDAP backend).
- **Consistent security posture**: All services benefit from Authelia's security features (brute-force protection, session management, audit logging).
- **Simplified onboarding**: New services follow a documented pattern (see `40-runbooks/deploy-new-k3s-service.md`).

### Negative

- **Authelia is a single point of failure**: If Authelia is down, OIDC-dependent services cannot authenticate new sessions (existing sessions may continue depending on token TTL).
- **N8N limitations**: N8N community edition lacks OIDC, forcing the less elegant forward-auth approach. This means N8N has no user identity context from the auth layer.
- **Secret duplication**: Client secrets exist in two forms (plaintext for services, argon2 hash for Authelia), increasing the surface area for secret management.
- **Environment-specific configuration**: Redirect URIs and issuer URLs differ per environment, requiring Kustomize patches for each overlay.

### Risks

- **JWKS key rotation**: No automated rotation mechanism yet. Manual rotation requires updating SOPS, redeploying Authelia, and potentially invalidating active tokens.
- **Authelia OIDC maturity**: Authelia's OIDC provider is relatively new. Breaking changes in Authelia upgrades may require client reconfiguration.

## References

- [Authelia OIDC Documentation](https://www.authelia.com/configuration/identity-providers/openid-connect/)
- [MinIO OIDC Configuration](https://min.io/docs/minio/linux/operations/external-iam/configure-openid-external-identity-management.html)
- [Gitea OAuth2 Provider Setup](https://docs.gitea.com/usage/authentication)
- ADR-014: Secrets Management Strategy (SOPS + toolkit)
- ADR-015: VPS K3s Migration Strategy
