---
id: lesson-689-netplan-merges-nameservers-across-files-so-a-leftover-file-rewrites-your-resolvers
type: lesson
status: active
created: "2026-11-02"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, netplan, systemd-resolved, ansible]
---

# netplan merges nameservers across files, so a leftover file rewrites your resolvers

**Context**: `base_system` renders `/etc/netplan/50-cloud-init.yaml` on the LAN nodes. #2909 was filed saying no role managed bee's netplan, because its resolvers matched no declaration.

**Problem**: A role did manage it. The Ubuntu installer's `00-installer-config.yaml` was still beside the role's file, and netplan appends list values across files instead of replacing them, so `8.8.8.8 1.1.1.1` plus `172.16.1.1 8.8.8.8` became a live `8.8.8.8 1.1.1.1 172.16.1.1`. Each file looked right alone. The role's own default also mixed the LAN gateway with a public server, the coin flip of lesson-682, on ace1 and ace2 as well. That public entry was no fallback: every node's default route goes through the gateway. It only took over when Pi-hole alone failed, and resolved then stayed on it.

**Solution**: `base_system` owns the whole directory and removes files it did not write, and the only resolver is the gateway, what DHCP gives every LAN client (ADR-075). Staging names are unaffected, since they route over `tailscale0`. The bare `netplan apply` handler became inline tasks behind a revert: back up, arm a `systemd-run` timer, write, `netplan generate`, apply, prove a name resolves, disarm. A drill on ace2 forced the probe to fail, and the timer restored the old files 180 s later. Bee and ace1 then ran it, each with a second run at `changed=0`. #2909.

**Rule**: Read what netplan merged, not one file: a list value in `/etc/netplan` is the union of every file that sets it. A role that owns a config directory must own all of it. Before keeping a "fallback" server, trace the route to it and what happens after it answers once.

**Tags**: `#netplan` `#systemd-resolved` `#issue-2909`
