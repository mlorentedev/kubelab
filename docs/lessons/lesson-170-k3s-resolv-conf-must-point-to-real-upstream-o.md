---
id: lesson-170-k3s-resolv-conf-must-point-to-real-upstream-o
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, k3s, dns, systemd-resolved, coredns, debugging]
---

# K3s resolv-conf must point to real upstream on systemd-resolved hosts

**Context:** K3s pods couldn't resolve external domains (acme-v02.api.letsencrypt.org). CoreDNS forwarded to `/etc/resolv.conf` which contained `127.0.0.53` (systemd-resolved stub). From inside the pod, 127.0.0.53 is the pod's own loopback — no DNS server there.

**Problem:** K3s config.yaml had no `resolv-conf` setting. Defaulted to host `/etc/resolv.conf` which is the stub on systemd-resolved hosts.

**Solution:** Added `resolv-conf: "/run/systemd/resolve/resolv.conf"` to K3s config.yaml template. This file contains the real upstream DNS servers (Hetzner: 185.12.64.1, 185.12.64.2). Requires K3s restart + CoreDNS rollout restart.

**Rule:** On systemd-resolved hosts, K3s must use `/run/systemd/resolve/resolv.conf`, not `/etc/resolv.conf`.
**Tags:** `#k3s` `#dns` `#systemd-resolved` `#coredns` `#debugging`
