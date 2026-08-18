---
id: lesson-202-uptime-kuma-status-page-api-is-public
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: observability
tags: [kubelab, observability]
---

# Uptime Kuma status page API is public

**Context**: Integrating Uptime Kuma status into Homepage.

**Problem**: Expected to need API auth for Uptime Kuma status data.

**Solution**: Status page API is public by design. Slug is `kubelab`. No auth token needed.

**Rule**: Check if monitoring tools expose public status endpoints before setting up authenticated API integrations.
