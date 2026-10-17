---
id: lesson-506-a-health-check-against-localhost-fails-once-the-port-binds-to-the-tailnet
type: lesson
status: active
created: "2026-10-02"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, uptime-kuma, rpi3, tailscale]
---

# A health check against `localhost` fails once the port binds to the tailnet, and only on the first provision after

**Context**: rpi3 was provisioned on 2026-10-02 for the first time since #1278 (2026-08-22), to clear the drift #1983 found. In between, #959 had moved Uptime Kuma's published port from `"3001:3001"` to `"{{ tailscale_ip }}:3001:3001"`, because a ufw rule cannot restrict a Docker-published port and only the bind address can.

**Problem**: The provision failed at `Verify Uptime Kuma health` with `Connection refused` on `http://localhost:3001`, after 5 retries. Uptime Kuma itself was fine: the container was `healthy` (its own probe runs inside the container, where `localhost:3001` is the app) and answered 302 at `100.64.0.6:3001`. The host's loopback had nothing listening, because the port was no longer published there. The check was written for the old bind, and the PR that moved the bind never ran against rpi3, so nothing turned red until a provision that had been put off for six weeks.

**Solution**: The check asks the address the port is bound to, `http://{{ tailscale_ip }}:{{ uptime_kuma_port }}`, as the `glances`, `beelink_services` and `agent_stack` roles already did. `tests/test_health_checks_use_the_bind_address.py` finds every role whose Compose templates publish ports only on `{{ tailscale_ip }}` and fails if any `uri` task in it targets `localhost`, `127.0.0.1` or `[::1]`. It failed on rpi3 before the fix and passed after.

**Rule**: When a port's bind address changes, every probe of that port from the host changes with it, in the same PR. A container `healthy` status does not tell you which addresses outside the container can reach the port. And a node left unprovisioned stores up every change merged since its last run, so the first provision after a long gap surfaces them together, on a node you may not want failing (here, the external monitor). Dry-run it first and read the failures as a backlog.

**Tags**: `#ansible` `#uptime-kuma` `#tailscale` `#pr-959` `#issue-1983`
