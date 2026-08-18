---
id: lesson-226-docker-compose-volume-naming-mismatch-destroy
type: lesson
status: active
created: "2026-03-27"
owner: manu
tags: [kubelab, lesson, docker, ansible, data-loss, volumes]
---

# Docker Compose volume naming mismatch destroys data on migration

**Context:** Migrating RPi3 services from ad-hoc docker run to Ansible-managed Docker Compose
**Problem:** Ad-hoc containers used volume name `uptime-kuma_uptime_kuma_data`. Compose generated `uptime_kuma_data` (different naming convention). New empty volume was mounted, data appeared lost. Uptime Kuma showed setup wizard instead of existing dashboard.
**Solution:** Use `external: true` with the exact original volume name in compose template. For migration: copy data between volumes with alpine container, then restart. For future: always check `docker volume ls` before provisioning nodes with existing data.
**Tags:** `#docker` `#ansible` `#data-loss` `#volumes`
