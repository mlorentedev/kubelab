---
id: lesson-660-an-address-check-says-where-a-run-lands-not-the-path-its-packets-take
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, ansible, tailscale, networking]
---

# An address check says where a run lands, not the path its packets take

**Context**: ADR-075 D7 requires every edge run to come over the homelab LAN, because applying the uplink can cut a session that rides the tailnet. The play checked that `ansible_host` was the edge's LAN address.

**Problem**: The laptop on the switch passed that check while its packets rode the tailnet. It accepts the subnet route the edge advertises, and Tailscale's table 52 is looked up before the main table, so the LAN address was reached through `tailscale0` from 100.64.0.1. The `kubelab-edge-lan` profile that routes the LAN first does not autoconnect: after a replug, "Wired connection 1" had the adapter. A second trap sat behind the first. Ansible keeps an SSH session open for 60 s under a socket name built from host, port and user, with no pid, so runs share it. A session opened over the tailnet is stranded once the route moves, and the next run hangs on its first SSH call. A dry run that opened its session 20 s before the profile came up did exactly that.

**Solution**: The play asks the controller's kernel which source address it would use (`route-source.py`: a UDP `connect`, no packet sent) and refuses a tailnet source before any role. It then runs `meta: reset_connection`, so the session it continues on is opened on the path just read (#2801). Live: refused from `100.64.0.1` before `make edge-lan-link`, passed from `172.16.1.91` after it.

**Rule**: To require a path, read the path: the source address the kernel picks for the destination, not the destination. When the path can change between runs, close any reused session after reading it. A meta task takes no `when`, so make the reset unconditional.

**Tags**: `#ansible` `#tailscale` `#pr-2805`
