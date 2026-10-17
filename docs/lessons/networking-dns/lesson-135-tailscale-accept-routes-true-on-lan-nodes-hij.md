---
id: lesson-135-tailscale-accept-routes-true-on-lan-nodes-hij
type: lesson
status: active
created: "2026-03-18"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Tailscale accept-routes=true on LAN nodes hijacks reply routing and kills inbound traffic

**Context:** Provisioning bare-metal homelab nodes (ace1, ace2) on 172.16.1.0/24. RPi4 advertises that subnet as a Tailscale subnet route. Ansible playbooks had tailscale_accept_routes: true for all nodes.
**Problem:** When tailscaled ran on ace2 (172.16.1.5) with --accept-routes=true, all inbound LAN traffic died. Outbound worked. Root cause: Tailscale installed 172.16.1.0/24 in routing table 52 via tailscale0 at priority 5270 (before main table). Reply packets to inbound LAN requests got routed through the Tailscale tunnel to RPi4 instead of directly out enp1s0. Asymmetric routing caused packet drops. Debugging was hard because outbound worked fine and iptables/rp_filter were red herrings.
**Solution:** Set --accept-routes=false on nodes that are physically on the advertised subnet. Live fix: `tailscale set --accept-routes=false`. Ansible fix: `tailscale_accept_routes: false` in provision-ace1.yml and provision-ace2.yml. Rule: accept-routes=true only for nodes NOT on the advertised subnet (workstation, VPS). Documented in CLAUDE.md gotchas and 30-architecture/infra/networking-topology.md with full 3-network topology diagram.
**Tags:** `#tailscale` `#networking` `#routing` `#ansible` `#bare-metal` `#debugging`
