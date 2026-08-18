---
id: lesson-204-glances-docker-image-tag-4-full-doesn-t-exist
type: lesson
status: active
created: "2026-03-23"
owner: manu
tags: [kubelab, lesson]
---

# Glances Docker image tag 4-full doesn't exist

**Context**: Deploying Glances agent on nodes.

**Problem**: Used `4-full` tag which doesn't exist. Silent pull failure.

**Solution**: Correct tag is version-specific: `4.5.2-full`.

**Rule**: Always verify Docker image tags exist before deploying. Use exact version tags, not assumed patterns. `docker pull --dry-run` or check the registry directly.
