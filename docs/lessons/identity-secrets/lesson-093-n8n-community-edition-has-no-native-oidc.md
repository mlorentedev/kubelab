---
id: lesson-093-n8n-community-edition-has-no-native-oidc
type: lesson
status: active
created: "2026-03-01"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# N8N Community Edition Has No Native OIDC

**Context**: Planning centralized auth via Authelia OIDC for all services.

**Problem**: N8N community edition does not support OIDC/OAuth2 authentication natively. Only enterprise N8N has SAML/LDAP support.

**Solution**: Use Authelia forward-auth middleware (`one_factor` policy) on N8N's IngressRoute. Users authenticate at the Authelia gate before reaching N8N. N8N itself still requires its own initial account setup, but the Traefik layer ensures only authenticated users reach it.

**Rule**: When a service doesn't support OIDC, use Authelia forward-auth as a security gate. This isn't true SSO (the service still has its own session), but it provides centralized access control. Check the service's auth capabilities BEFORE planning the OIDC integration.

---
