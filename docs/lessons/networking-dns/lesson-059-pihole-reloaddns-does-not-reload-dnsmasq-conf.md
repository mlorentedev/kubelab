---
id: lesson-059-pihole-reloaddns-does-not-reload-dnsmasq-conf
type: lesson
status: active
created: "2026-02-21"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# pihole reloaddns Does NOT Reload dnsmasq Config Files

**Context**: Adding conditional forwarding in Pi-hole for `kubelab.live` → CoreDNS.

**Problem**: After creating/modifying files in `/etc/dnsmasq.d/`, running `pihole reloaddns` doesn't reload them. The query kept returning NXDOMAIN. `pihole reloaddns` only reloads blocklists (gravity), not dnsmasq configuration files.

**Solution**: `docker restart pihole` (or `pihole-FTL --config dns.restart` in Pi-hole v6). Only a full restart reloads `/etc/dnsmasq.d/` files.

**Rule**: For dnsmasq config changes (`/etc/dnsmasq.d/`), always `docker restart pihole`. `pihole reloaddns` is ONLY for gravity/blocklists. Verify with `dig @127.0.0.1 <domain>` after restart.
