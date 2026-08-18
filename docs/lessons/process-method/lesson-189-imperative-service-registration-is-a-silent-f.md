---
id: lesson-189-imperative-service-registration-is-a-silent-f
type: lesson
status: active
created: "2026-03-25"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Imperative service registration is a silent failure vector

**Context**: CrowdSec bouncer was registered imperatively via `cscli bouncers add` in a postStart hook with `2>/dev/null || true`. Gitea OIDC was registered manually via `configure_oidc.py`.

**Problem**: CrowdSec LAPI lost bouncer registration after a pod restart (DB state lost). The postStart hook swallowed the error (`|| true`). Result: bouncer returned 403 to ALL traffic for 6 days, including Uptime Kuma monitoring. No alerts because the failure was silent. Gitea had the same pattern risk — OIDC provider stored only in SQLite, populated by a manual script.

**Solution**: (1) CrowdSec: replaced imperative `cscli bouncers add` generation in credentials.py with static `secrets.token_urlsafe(32)`. Both LAPI and bouncer read from same K8s Secret. PostStart does idempotent delete+add without swallowing errors. (2) Gitea: bootstrap script in ConfigMap handles admin user creation + migration (admin→manu via SQLite) + OIDC provider registration. All idempotent, all on every pod start.

**Rule**: Never use `|| true` or `2>/dev/null` in postStart hooks — silent failures cause cascading outages. Service registration must be: (1) declarative (shared secrets from SOPS), (2) idempotent (delete+add or update), (3) visible (errors propagate to pod status). If a service stores config in a runtime DB, the postStart hook must re-apply it on every start.
