---
id: lesson-030-uptime-kuma-container-caches-dns-restart-afte
type: lesson
status: active
created: "2026-03-19"
owner: manu
tags: [kubelab, lesson]
---

# Uptime Kuma container caches DNS — restart after DNS changes

**Context**: After migrating staging DNS from Cloudflare to Headscale split DNS + CoreDNS, Uptime Kuma monitors showed staging services as "down" (404) despite `curl` from RPi3 host returning 200.

**Problem**: Docker containers inherit `/etc/resolv.conf` at start time. Uptime Kuma's Node.js runtime caches DNS and HTTP connections. After DNS infrastructure changes (new zones, IP changes), the container keeps using stale resolution until restarted.

**Solution**: `docker restart uptime-kuma` on RPi3. All monitors recovered immediately.

**Rule**: After any DNS infrastructure change (split DNS zones, CoreDNS config, IP changes), restart monitoring containers. Add to ANSIBLE-018 maintenance playbook.
