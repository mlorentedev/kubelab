---
id: lesson-196-homepage-allowed-hosts-required-for-next-js-1
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: apps-web
tags: [kubelab, apps-web]
---

# HOMEPAGE_ALLOWED_HOSTS required for Next.js 15.x

**Context**: Homepage uses Next.js 15.x internally.

**Problem**: Next.js 15.x host validation rejects requests from unknown domains. Homepage pod crashes or returns errors without this env var.

**Solution**: Set `HOMEPAGE_ALLOWED_HOSTS` env var with all domains the dashboard serves.

**Rule**: Any Next.js 15+ app behind a reverse proxy needs explicit host allowlisting. Check the framework's host validation requirements before deploying behind Traefik/Nginx.
