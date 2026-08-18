---
id: lesson-117-traefik-v3-6-does-not-support-maxbackups-maxs
type: lesson
status: active
created: "2026-03-15"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# Traefik v3.6 does not support maxBackups/maxSize in accessLog config

**Context:** Upgrading Traefik from v3.0 to v3.6 via Ansible traefik_vps role
**Problem:** Added maxSize and maxBackups fields to accessLog config in traefik.yml template. Traefik v3.6 crashed with 'field not found, node: maxBackups'. These fields don't exist in Traefik's static config schema.
**Solution:** Removed maxSize and maxBackups from traefik.yml template. Log rotation for Traefik access logs should be handled externally (logrotate on the host, or a Docker logging driver). The accessLog config only supports filePath, format, and fields.
**Tags:** `#traefik` `#ansible` `#config`
