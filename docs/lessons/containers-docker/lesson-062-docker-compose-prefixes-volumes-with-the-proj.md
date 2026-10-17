---
id: lesson-062-docker-compose-prefixes-volumes-with-the-proj
type: lesson
status: active
created: "2026-02-21"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker]
---

# Docker Compose Prefixes Volumes with the Project Name

**Context**: Migrating Pi-hole from `docker run` to Docker Compose on RPi 4.

**Problem**: The original volumes were named `pihole_data` and `pihole_dnsmasq`. Compose prefixed them with the directory name → created empty `pihole_pihole_data` and `pihole_pihole_dnsmasq`. Pi-hole started without config → DNS broken.

**Solution**: Mark volumes as `external: true` in compose.yml. Compose reuses them without prefix.

**Rule**: Whenever migrating from `docker run` to compose with existing volumes, use `external: true`. Verify with `docker volume ls` that no duplicate volumes were created.

---
