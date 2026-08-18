---
id: lesson-203-authelia-restart-invalidates-all-browser-sess
type: lesson
status: active
created: "2026-03-23"
owner: manu
tags: [kubelab, lesson]
---

# Authelia restart invalidates all browser sessions

**Context**: `make deploy-k8s` does a `rollout restart` on all deployments including Authelia.

**Problem**: Restarting Authelia invalidates all browser sessions. Users get 403 Forbidden and must clear the `authelia_session` cookie manually.

**Solution**: Short-term: added auto-restart in Makefile. Long-term: RELIAB-001 (initContainer wait-for-redis) ensures Authelia reconnects to Redis session store on restart, preserving sessions.

**Rule**: Stateful auth services (Authelia, Keycloak) must persist sessions externally (Redis). Restarting the pod should not invalidate user sessions. Test session persistence across restarts before going to prod.
