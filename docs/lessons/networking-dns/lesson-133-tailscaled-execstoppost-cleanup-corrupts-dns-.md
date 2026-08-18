---
id: lesson-133-tailscaled-execstoppost-cleanup-corrupts-dns-
type: lesson
status: active
created: "2026-03-17"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# tailscaled ExecStopPost cleanup corrupts DNS state on crash

**Context:** ADR-023 Phase 1 — tailscaled wouldn't restart after crash/power-cycle on ace2
**Problem:** When tailscaled crashes or is killed (power cycle), ExecStopPost runs `tailscaled --cleanup` which tries to remove DNS routes for tailscale0 interface. If the interface doesn't exist (crash/unclean shutdown), cleanup fails with 'route ip+net: no such network interface' and corrupts state. Next start attempt also fails because it runs cleanup first.
**Solution:** Disable ExecStopPost via systemd override: `sudo systemctl edit tailscaled` → add `[Service]\nExecStopPost=` (empty value overrides). Also need `sudo systemctl daemon-reload`. This prevents cleanup from running. /etc/default/tailscaled uses PORT and FLAGS variables (not TS_EXTRA_ARGS). Default: PORT=0, FLAGS="".
**Tags:** `#tailscale` `#systemd` `#dns` `#debugging`
