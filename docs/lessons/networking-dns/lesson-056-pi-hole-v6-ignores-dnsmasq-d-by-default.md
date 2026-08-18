---
id: lesson-056-pi-hole-v6-ignores-dnsmasq-d-by-default
type: lesson
status: active
created: "2026-02-21"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Pi-hole v6 Ignores dnsmasq.d by Default

**Context**: Configuring Pi-hole to forward `*.staging.kubelab.live` to CoreDNS (port 5353) via a file in `/etc/dnsmasq.d/`.

**Problem**: Pi-hole v6 uses FTL as its own resolver, not dnsmasq. By default `etc_dnsmasq_d = false` in `pihole.toml`, so any file in `/etc/dnsmasq.d/` is completely ignored. Also, `pihole restartdns` no longer exists in v6 — the command is `pihole reloaddns`.

**Solution**: Edit `pihole.toml` → `etc_dnsmasq_d = true`, then `docker restart pihole`. The conditional forward: `server=/staging.kubelab.live/172.17.0.1#5353` (use Docker bridge gateway IP, not 127.0.0.1 — inside the container, localhost is the container itself).

**Rule**: Pi-hole v6 ≠ Pi-hole v5. Always check `pihole.toml` for features that used to be automatic. And inside a Docker container, `127.0.0.1` ≠ host — use `172.17.0.1` to reach the host.
