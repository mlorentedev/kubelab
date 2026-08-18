---
id: lesson-046-docker-anonymous-volumes-inherit-image-owners
type: lesson
status: active
created: "2026-02-09"
owner: manu
tags: [kubelab, lesson]
---

# Docker Anonymous Volumes Inherit Image Ownership

**Context**: Building Docker images for web apps (Astro, Jekyll).

**Problem**: The build stage runs as root, creating `node_modules/`, `.vite/`, `.astro/` with root ownership. Even though compose has `user: "1000:1000"`, anonymous volumes created during build retain root ownership, causing permission errors at runtime.

**Solution**: Use `USER node` in the Dockerfile build stage, not just the `user:` directive in compose. Volumes must be created with the correct user from the start.

**Rule**: Always verify ownership of anonymous volumes in multi-stage images. `docker compose exec <svc> ls -la /app/` before looking for code bugs.
