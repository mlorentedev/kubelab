---
id: "lesson-559-a-resolver-entry-must-name-who-serves-the-name-not-where-the-workload-runs"
type: lesson
status: active
title: "A resolver entry must name who serves the name, not where the workload runs"
created: "2026-10-11"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, coredns, uptime-kuma, backup]
---

# A resolver entry must name who serves the name, not where the workload runs

**Context**: rpi4's CoreDNS answers the prod zone from an explicit `hosts` list, so LAN nodes reach prod over the tailnet. After a power cycle, ace2's backup heartbeat to `status.kubelab.live` failed with `connect failed after 7 ms`, while the backup itself succeeded.

**Problem**: The entry still listed Uptime Kuma under "bare-metal services" with rpi3's tailnet address. The workload does run on rpi3, but on `:3001`. Its public name has been a prod IngressRoute since #121, so 443 on rpi3 refuses. The failure was intermittent: systemd-resolved sticks to whichever link server last answered, `172.16.1.1` (stale entry) or `8.8.8.8` (public, correct). Heartbeats passed until a reboot made the LAN resolver current again.

**Solution**: Map the name to `node_ips.vps` with the other K3s routes (#2212). `tests/test_coredns_prod_zone_targets.py` renders the prod zone from the SSOT, kustomizes the prod overlay, and fails when any name with a prod IngressRoute resolves to another node.

**Rule**: A DNS record answers "who terminates this name", which changes when a service moves behind a router, even when the workload stays where it is. When fronting moves, grep every resolver that pins the name (CoreDNS hosts, `/etc/hosts`, split DNS). Prefer a test that derives the expected target from the routes over a comment that classifies the service.

**Tags**: `#dns` `#coredns` `#issue-2212`
