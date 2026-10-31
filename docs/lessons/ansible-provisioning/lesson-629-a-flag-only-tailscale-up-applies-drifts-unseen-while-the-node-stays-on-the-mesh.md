---
id: lesson-629-a-flag-only-tailscale-up-applies-drifts-unseen-while-the-node-stays-on-the-mesh
type: lesson
status: active
created: "2026-10-26"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, tailscale, idempotence]
---

# A flag only `tailscale up` applies drifts unseen while the node stays on the mesh

**Context**: The `tailscale` role runs `tailscale up --reset` with the play's
`--accept-dns`, `--accept-routes` and `--advertise-routes`, but only on a node
that is off the mesh. A node that is already Running skips it, so that a
provision does not re-authenticate a working node. During the NET-005 bring-up
(#2685), each node's prefs were read with `tailscale debug prefs`, filtered on
the node.

**Problem**: rpi3 held `RouteAll: true` (`--accept-routes=true`) while its play
declared `false`. Every provision of rpi3 reported `ok` and `changed=0`,
because no task compared the running prefs with the declared ones. The drift
was harmless on rpi3, which sits on the lab Wi-Fi and not on `lan_cidr`. The
same drift on a LAN node is the table-52 hijack that breaks all of its inbound
LAN traffic. The next rejoin would also have applied it without any warning,
since `--reset` sets the whole flag set at once.

**Solution**: The role reads the three fields on a Running node. The node's
keys live under `Persist` in the same output, so the filter runs on the node
and only `RouteAll`, `CorpDNS` and the sorted `AdvertiseRoutes` leave it. When
any of them differs from the play, the role runs `tailscale set`, which
changes prefs in place with no re-authentication and no `--reset`. An empty
`--advertise-routes=` withdraws a route the play no longer declares. On rpi4,
which matches its play, the first run gave `changed=0` with the converge
skipped.

**Rule**: A task that is skipped once the system reaches a state also stops
enforcing what it set on the way there. Pair each such task with a read of the
live value and a convergence step, or the declaration describes the first
provision and nothing after it.

**Tags**: `#tailscale` `#idempotence` `#issue-2685`
