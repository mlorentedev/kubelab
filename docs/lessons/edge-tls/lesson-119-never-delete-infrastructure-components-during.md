---
id: lesson-119-never-delete-infrastructure-components-during
type: lesson
status: active
created: "2026-03-15"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# Never delete infrastructure components during cleanup without verifying dependencies

**Context:** VPS cleanup after Traefik migration — removed nginx container and error-pages config
**Problem:** Removed nginx container and nginx.yml from Traefik dynamic config because the container was in 'Exited' state. All routes referenced 'error-pages' middleware (defined in nginx.yml), causing Traefik to reject all routers. The 'Exited' state was incidental — the container was needed.
**Solution:** Restarted nginx container and restored nginx.yml. Rule: before removing ANY component, grep for references across all config files. An 'Exited' container is not necessarily unused — it may need to be restarted, not deleted.
**Tags:** `#docker` `#traefik` `#cleanup` `#outage`
