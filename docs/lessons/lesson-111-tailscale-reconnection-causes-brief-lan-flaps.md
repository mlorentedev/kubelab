---
id: lesson-111-tailscale-reconnection-causes-brief-lan-flaps
type: lesson
status: active
created: "2026-03-14"
owner: manu
tags: [kubelab, lesson]
---

# Tailscale reconnection causes brief LAN flaps

**Context:** After 5 days offline, all homelab nodes (bee, jet1, k3s-server/agents) reconnected to Tailscale simultaneously. Uptime Kuma reported intermittent DOWN on LAN monitors (172.16.1.x).

**Root cause:** Tailscale modifies routing tables when reconnecting. During the 5-30 second reconnection window, packets may be dropped or misrouted. With all nodes reconnecting at once, the flapping compounds.

**Resolution:** Self-heals within 2-5 minutes. No action needed. Uptime Kuma will show brief outages.

**Rule:** After a mass reconnection event (power outage, Headscale restart), expect 2-5 minutes of Uptime Kuma flapping. Do not troubleshoot individual nodes until the mesh stabilizes.
