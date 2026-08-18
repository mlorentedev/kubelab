---
id: lesson-262-docker-port-bind-to-interface-specific-ip-is-
type: lesson
status: active
created: "2026-05-23"
owner: manu
tags: [kubelab, lesson, ansible, docker, tailscale, networking, ollama, ansible-025]
---

# Docker port bind to interface-specific IP is fragile under interface flap

**Context:** ace2 ollama compose used `ports: ["100.64.0.5:11434:11434"]` to constrain the listener to Tailscale interface — implicit "VPN-only" via bind constraint. Worked fine in steady state.
**Problem:** tailscaled flapped briefly during AI-001 PR-C smoke (re-key / NAT rebind / health-check retry). The momentary loss of `100.64.0.5` from `tailscale0` broke dockerd's port binding. The container died, and `restart: unless-stopped` couldn't recover because `cannot assign requested address` — Linux IP-specific binds DO NOT auto-rebind after interface recovery; the container needs full recreation. Dockerd looped restarting for hours until manual intervention. Meanwhile public path returned HTTP 502. Discovered 2026-05-23 (ANSIBLE-025, closed by PR #199).
**Solution:** Use `network_mode: host` + listen on `0.0.0.0` + UFW restrict by source CIDR. The bind lives in the kernel's global port table, decoupled from any one interface. tailscaled flaps no longer break the listener. Security preserved by UFW `allow PORT/tcp from tailscale_cidr` + `from lan_cidr` (default-deny inherited from `base_system` role). Equivalent external reachability (VPN + LAN only), but resilient to flaps. **Implicit security via bind constraint is the worst kind of security — it breaks silently.** Always make it explicit (firewall, RBAC, etc.).
**Tags:** `#ansible` `#docker` `#tailscale` `#networking` `#ollama` `#ansible-025`
