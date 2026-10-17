---
id: lesson-112-usb-eth-rpi4-router-dhcp-not-responding
type: lesson
status: active
created: "2026-03-14"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# USB ETH RPi4 — router DHCP not responding

**Context:** After RPi4 SD reflash, USB ETH adapter (enx00249b1b0d6b, ASIX AX88179) is link UP but receives no DHCP lease from router. WiFi (wlan0) works fine on the same router.

**Status:** UNRESOLVED. L2 block confirmed — not L3/DHCP. DHCP Discover packets leave the adapter (tcpdump confirmed) but router never responds. ARP also fails with static IP. MAC `00:24:9b:1b:0d:6b` appears in Xfinity panel as "Offline", not blocked/paused.

**Ruled out:** driver, link layer, netplan config, MAC filtering in router panel, bridge mode, DHCP client-ID type.

**Hypothesis:** Router port dead OR Xfinity firmware silently filtering the MAC at L2 switching level.

**Impact:** Non-blocking. WiFi provides full connectivity. USB ETH is redundancy + speed (Gigabit vs WiFi ~50Mbps).

**Next step:** Connect a different device to the same cable + same router port. If it gets IP → MAC-specific filtering (try MAC spoofing + contact Xfinity). If not → dead port (try different port).
