---
id: lesson-033-pi-hole-conditional-forwarding-must-include-a
type: lesson
status: active
created: "2026-03-19"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Pi-hole conditional forwarding must include all CoreDNS zones

**Context**: Added `staging.mlorente.dev` zone to CoreDNS Corefile. DNS queries from Tailscale MagicDNS resolved correctly, but queries from inside Docker containers on RPi3 returned NXDOMAIN.

**Problem**: Pi-hole sits in front of CoreDNS on RPi4. `pihole-forwarding.conf` only had `server=/kubelab.live/...` — no forwarding for `staging.mlorente.dev`. Queries for non-kubelab domains went to upstream DNS (1.1.1.1) instead of CoreDNS.

**Solution**: Add `server=/staging.mlorente.dev/172.17.0.1#5353` to pihole-forwarding.conf. Now driven by `staging_zones` loop in template.

**Rule**: Every CoreDNS zone must have a matching Pi-hole forwarding entry. Use the `staging_zones` SSOT list to generate both in lockstep.
