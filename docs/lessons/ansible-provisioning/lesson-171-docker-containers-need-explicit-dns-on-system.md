---
id: lesson-171-docker-containers-need-explicit-dns-on-system
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Docker containers need explicit DNS on systemd-resolved hosts

**Context:** Headscale Docker container couldn't resolve `controlplane.tailscale.com` — got "connection refused" on 127.0.0.53:53.

**Problem:** Same as K3s — Docker inherits host `/etc/resolv.conf` stub. Container's 127.0.0.53 is its own loopback.

**Solution:** Added `dns:` directive to Headscale docker-compose.yml.j2 with explicit DNS servers from common.yaml (1.1.1.1, 8.8.8.8). Parameterized as `docker_dns_servers` role variable.

**Rule:** All Docker Compose services on systemd-resolved hosts need explicit `dns:` in compose. Use role defaults with public DNS as fallback.
**Tags:** `#docker` `#dns` `#systemd-resolved` `#headscale` `#ansible`
