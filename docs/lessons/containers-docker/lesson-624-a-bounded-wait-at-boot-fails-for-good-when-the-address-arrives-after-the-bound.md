---
id: lesson-624-a-bounded-wait-at-boot-fails-for-good-when-the-address-arrives-after-the-bound
type: lesson
status: active
created: "2026-10-26"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, systemd, tailscale, boot]
---

# A bounded wait at boot fails for good when the address arrives after the bound

**Context**: Every stack published on a node's Tailscale address has a oneshot unit that waits for the address (`wait-for-tailscale-addr.sh`, about two minutes) and then brings the stack up. It exists because dockerd resurrects containers at boot before the address exists, and the bind is dropped without an error (lesson-308). The lab then moved site, behind a new edge (#2661).

**Problem**: The fleet booted before the tailnet was reachable, since the edge's uplink was still behind a captive portal and rpi3's only network, the lab Wi-Fi, did not exist yet. Each unit's wait timed out in `ExecStartPre`, so `ExecStart` never ran, and nothing runs a oneshot again once it has failed at boot. A day later Uptime Kuma on rpi3, Gitea on bee and Glances on every homelab node were `Up (healthy)`, attached to no network (`PortBindings` 1, `NetworkSettings.Ports` 0, an empty `/proc/net/route`). Kuma could neither probe nor notify, so nothing reported the outage. The wait was correct for a race of seconds and silent for a delay of hours.

**Solution**: Retry the unit (`Restart=on-failure`, `RestartSec=30`). This was measured with a transient oneshot whose `ExecStartPre` failed: it sat in `activating (auto-restart)` and went `active` within one retry of the condition holding. The unit also recreates its stack (`--force-recreate`), since plain `up -d` adopts the unbound container. And the provision starts the unit, because enabling a unit never starts it, and compares requested bindings with effective ones (`_includes/compose-port-drift.yml`). `tests/test_tailscale_bound_boot_units.py` holds every unit that waits for the address to all of this. #2500.

**Rule**: A boot step that waits for something with a bound needs a retry after the bound, unless what it waits for is local to the node. A failed oneshot is final until someone starts it, and a precondition from the network can arrive hours late. Ask what happens when the thing arrives one second after the timeout: if the answer is "nothing, until the next boot", the timeout turned a delay into an outage.

**Tags**: `#systemd` `#tailscale` `#boot-race` `#issue-2500`
