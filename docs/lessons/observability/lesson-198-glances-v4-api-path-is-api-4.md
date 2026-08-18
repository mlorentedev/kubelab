---
id: lesson-198-glances-v4-api-path-is-api-4
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: observability
tags: [kubelab, observability]
---

# Glances v4 API path is /api/4/

**Context**: Configuring Homepage Glances widget for node metrics.

**Problem**: Homepage defaults to `/api/3/`. Glances v4 moved to `/api/4/`. Widget silently returns no data.

**Solution**: Set `version: 4` in Homepage Glances widget config.

**Rule**: When integrating monitoring agents, always verify the API version path. Silent failures (200 OK, empty data) are harder to debug than 404s.
