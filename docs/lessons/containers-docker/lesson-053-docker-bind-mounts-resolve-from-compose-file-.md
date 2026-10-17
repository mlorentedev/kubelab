---
id: lesson-053-docker-bind-mounts-resolve-from-compose-file-
type: lesson
status: active
created: "2026-02-14"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker]
---

# Docker Bind Mounts Resolve from Compose File Directory

**Context**: web and blog containers in restart loop, `package.json` / `Gemfile` not found.

**Problem**: Containers were created from `/home/manu/Projects/mlorente.dev/` (old project path). Relative bind mount paths (`../../../../apps/web/`) resolved to non-existent location.

**Solution**: Recreate containers from the correct working directory (`/home/manu/Projects/kubelab/`).

**Rule**: After renaming project directories, always recreate (not just restart) containers that use relative bind mounts.
