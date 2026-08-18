---
id: lesson-110-nftables-masquerade-must-include-wlan0-not-ju
type: lesson
status: active
created: "2026-03-14"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# nftables masquerade must include wlan0 (not just enx*)

**Context:** After RPi4 reflash, LAN nodes (172.16.1.0/24) had no internet. Ping to 8.8.8.8 from k3s-server returned 100% packet loss.

**Root cause:** nftables NAT rule only had `oifname "enx*" masquerade`. When USB ETH has no IP (DHCP from router not working), traffic exits via wlan0 — but wlan0 had no masquerade rule. Result: packets leave the RPi4 via WiFi but with source IP 172.16.1.x → router drops them (not its subnet).

**Fix:** Add `oifname "wlan0" masquerade` alongside the `enx*` rule. Both can coexist — Linux chooses the exit interface by route metric (enx* metric 100, wlan0 metric 600). The matching masquerade rule activates automatically.

**Updated `/etc/nftables.conf`:**
```
table inet nat {
    chain postrouting {
        type nat hook postrouting priority 100; policy accept;
        oifname "enx*" masquerade
        oifname "wlan0" masquerade
    }
}
```

**Rule:** RPi4 nftables MUST masquerade on ALL WAN interfaces, not just the primary. If a new WAN interface is added, add its masquerade rule too.
