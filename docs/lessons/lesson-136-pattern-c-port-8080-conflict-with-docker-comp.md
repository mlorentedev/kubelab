---
id: lesson-136-pattern-c-port-8080-conflict-with-docker-comp
type: lesson
status: active
created: "2026-03-20"
owner: manu
tags: [kubelab, lesson, traefik, k3s, pattern-c, ports]
---

# Pattern C port 8080 conflict with Docker Compose Traefik dashboard

**Context:** VPS K3s migration — K3s Traefik Pattern C uses 8080/8443 alongside Docker Compose Traefik on 80/443
**Problem:** Docker Compose Traefik dashboard binds port 8080, same as K3s Pattern C HTTP port. Both can't listen on 8080 simultaneously.
**Solution:** Remap Docker Compose Traefik dashboard to 9080 via traefik_vps role re-deploy BEFORE installing K3s. Playbook checks port binding, remaps, verifies 8080 is free, then proceeds with K3s install.
**Tags:** `#traefik` `#k3s` `#pattern-c` `#ports`
