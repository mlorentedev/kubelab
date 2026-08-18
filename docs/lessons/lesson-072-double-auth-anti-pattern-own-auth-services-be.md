---
id: lesson-072-double-auth-anti-pattern-own-auth-services-be
type: lesson
status: active
created: "2026-02-25"
owner: manu
tags: [kubelab, lesson]
---

# Double Auth Anti-Pattern: Own-Auth Services Behind Authelia

**Context**: Deciding whether to put portainer, gitea, minio, and n8n behind the Authelia ForwardAuth middleware.

**Problem**: Services with their own authentication system (portainer, gitea, n8n) placed behind Authelia result in two sequential login screens — users authenticate with Authelia, then authenticate again with the service. This is confusing UX and provides no security benefit since both auth systems protect the same resource.

**Solution**: Two patterns depending on the service:
- **Own auth only (dev/infra tools)**: bypass Authelia entirely. Use Authelia only at the network perimeter. Example: portainer, gitea.
- **OIDC SSO**: configure the service as an OIDC client against Authelia. Single login flow. Example: minio (supports OIDC natively), grafana.

**Rule**: Before wiring a service to Authelia ForwardAuth, check if it has native OIDC/OAuth2 support. If yes → configure SSO (single login). If no native SSO → bypass Authelia for that service. Never layer ForwardAuth on top of a service that has mandatory own-auth login.

---

*More entries will be added as the project progresses.*

---
