---
id: lesson-494-an-app-that-discovers-its-idp-once-must-start-after-it
type: lesson
status: active
created: "2026-09-30"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, vikunja, authelia, oidc, init-container, startup-order]
---

# An app that discovers its IdP once must start after it, and only the discovery document proves the IdP is up

**Context**: The operator reported that Vikunja on prod offered only its local login form, with no "KubeLab IDP" button, for the third time (#1783: staging 2026-09-22 and 2026-09-26, prod 2026-09-29, noticed 2026-09-30). `make restart-service SVC=vikunja ENV=prod` brought the button back each time.

**Problem**: Vikunja 1.0.0 fetches each OIDC provider's discovery document once, at startup. Loki showed the prod pod starting at 00:16 on 2026-09-29 while Traefik and Authelia were still coming up: `connection refused`, then `403`, then it gave up after 3 attempts. It then served `openid_connect.providers: []` from `/api/v1/info` for a day, while the pod stayed `1/1 Running`. Its image has no shell, so no probe can read that body to notice. Two traps came up while building the wait:

- Authelia answers **200** on paths it does not serve (`/nope` included), so a status check proves only that something answers.
- busybox 1.36's built-in `wget` TLS fails the handshake with prod Traefik (`alert 47`), so a busybox wait would wait forever on a healthy IdP.

**Solution**: an init container, `wait-for-idp`, on `postgres:16-alpine` (Alpine `wget` uses OpenSSL, and the image is already pinned and pulled). It reads the issuer URL from the same ConfigMap as Vikunja and loops until `.well-known/openid-configuration` returns a body containing `"authorization_endpoint"`. A pod waiting there is visibly not ready, rather than ready without SSO. `tests/test_vikunja_waits_for_idp.py` renders both overlays and fails if the wait disappears, stops checking the body, moves to busybox, or reads a different ConfigMap than the app.

**Rule**: when an app resolves a dependency once at startup and keeps the failure, readiness of that app says nothing about the dependency. Gate the start on the dependency's own contract (the document the app will parse), not on a port or a status code, and read it from the app's own configuration so the two cannot drift apart. Test the wait from the image you ship against the real endpoint: the TLS stack in a minimal image is part of the contract.

**Tags**: `#vikunja` `#authelia` `#oidc` `#init-container` `#issue-1783`
