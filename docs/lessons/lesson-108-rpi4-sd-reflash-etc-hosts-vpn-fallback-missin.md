---
id: lesson-108-rpi4-sd-reflash-etc-hosts-vpn-fallback-missin
type: lesson
status: active
created: "2026-03-14"
owner: manu
tags: [kubelab, lesson]
---

# RPi4 SD reflash — /etc/hosts VPN fallback missing

**Context:** Reflashed RPi4 SD card. Pre-config script (`configure-sd.sh`) wrote netplan, nftables, dnsmasq, sysctl — but `/etc/hosts` VPN fallback (`162.55.57.175 vpn.kubelab.live`) was missing on final verification.

**Root cause:** The `grep -q` guard checked for the entry but the `cat >>` append ran under sudo which failed silently in the non-interactive shell. The script reported OK but didn't write.

**Fix:** Added manually via `sudo bash -c 'cat >> /etc/hosts'`.

**Rule:** After ANY RPi4 SD reflash, ALWAYS verify `/etc/hosts` contains `162.55.57.175 vpn.kubelab.live` before booting. Without it, Tailscale can't bootstrap (circular dependency: DNS → Tailscale → DNS). This is the most critical single line on the RPi4.

**Related:** `40-runbooks/dns-homelab.md` §RPi4 Tailscale bootstrap circular dependency.
"
