---
id: lesson-165-enableservicelinks-false-required-for-n8n-sam
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# enableServiceLinks: false required for n8n (same as Authelia)

**Context:** n8n pod showed basic_auth popup after Authelia login. Logs showed "Invalid number value for N8N_PORT".

**Problem:** K8s service links inject `N8N_PORT=tcp://10.43.X.X:5678`. n8n expects a number. The invalid port causes n8n to malfunction and trigger basic auth fallback.

**Solution:** Add `enableServiceLinks: false` to n8n Deployment spec. Same pattern as Authelia.

**Rule:** Any service whose name collides with K8s service link env var prefixes needs `enableServiceLinks: false`. Check: Authelia (AUTHELIA_*), n8n (N8N_*), Redis (REDIS_*).
**Tags:** `#n8n` `#k8s` `#enableServiceLinks`
