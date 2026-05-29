---
id: networking-topology
type: architecture
status: active
created: "2026-03-18"
owner: manu
---

# KubeLab Network Topology

> Three networks, one mesh. Understanding when traffic flows where — and why `accept-routes` matters.

## The Three Networks

```
┌─────────────────────────────────────────────────────────────────────┐
│  NETWORK 1: Home LAN (10.0.0.0/24)                                 │
│  Router → Workstation (MSI), RPi4 (WAN side), RPi3                  │
│  Regular home internet. DHCP from router.                           │
└────────────────────────────┬────────────────────────────────────────┘
                             │ RPi4 bridges both networks
                             │ (eth0=10.0.0.x, eth1=172.16.1.1)
┌────────────────────────────▼────────────────────────────────────────┐
│  NETWORK 2: Homelab LAN (172.16.1.0/24)                             │
│  RPi4 (.1) → ace1 (.2) → bee (.3) → jet1 (.4) → ace2 (.5)         │
│  Isolated from home LAN. RPi4 provides internet + DNS (Pi-hole).    │
│  Physical Ethernet. Gigabit. Sub-millisecond latency.               │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Tailscale on every node
                             │ (WireGuard tunnels via Internet)
┌────────────────────────────▼────────────────────────────────────────┐
│  NETWORK 3: Tailscale Mesh (100.64.0.0/24 — CGNAT range)           │
│  msi (.1), vps (.2), bee (.3), k3s-server (.4), ace2 (.5),         │
│  rpi3 (.6), agent-1 (.7), jet1 (.8), agent-2 (.9), rpi4 (.10)     │
│  Encrypted WireGuard tunnels. Works from anywhere with internet.    │
│  Coordinated by Headscale (self-hosted) on VPS.                     │
└─────────────────────────────────────────────────────────────────────┘
```

## RPi4: The Bridge Node

RPi4 sits at the intersection of all three networks:

| Interface | Network | IP | Role |
|-----------|---------|-----|------|
| eth0 | Home LAN | 10.0.0.131 | Upstream internet |
| eth1 | Homelab LAN | 172.16.1.1 | Gateway for homelab nodes |
| tailscale0 | Tailscale | 100.64.0.10 | Mesh node + subnet router |

RPi4 runs `tailscale up --advertise-routes=172.16.1.0/24`. This tells Headscale:
*"I can reach 172.16.1.0/24 — if any mesh node needs to talk to that subnet, route it through me."*

## Subnet Routes and `accept-routes`

### What is a subnet route?

A Tailscale subnet route is an announcement: *"I am a gateway to this network."* It does NOT automatically affect other nodes. Other nodes must **opt in** with `--accept-routes=true`.

### What `accept-routes` does on a node

When a node runs `--accept-routes=true`, Tailscale:

1. Queries Headscale for all advertised subnet routes
2. Installs them in **routing table 52** (Tailscale's private table) via `tailscale0`
3. Adds **ip rules at priority 5210-5270** that consult table 52 **before** the main table

Result: the node routes traffic to advertised subnets through the Tailscale tunnel.

### When to use `accept-routes=true`

A node needs `accept-routes=true` when it is **NOT physically on** the advertised subnet and needs to reach it:

| Node | Location | `accept-routes` | Why |
|------|----------|-----------------|-----|
| **Workstation (MSI)** | Home LAN (not on 172.16.1.0/24) | `true` | Needs RPi4 tunnel to reach homelab |
| **VPS** | Hetzner cloud | `true` | Needs RPi4 tunnel to reach homelab |
| **RPi3** | Home LAN | `true` | Not on homelab LAN, needs tunnel |
| **ace1** | Homelab LAN (172.16.1.2) | `false` | Already on the subnet physically |
| **ace2** | Homelab LAN (172.16.1.5) | `false` | Already on the subnet physically |
| **bee** | Homelab LAN (172.16.1.3) | `false` | Already on the subnet physically |
| **jet1** | Homelab LAN (172.16.1.4) | `false` | Already on the subnet physically |
| **RPi4** | Homelab LAN (172.16.1.1) | `false` | IS the gateway — never accepts own routes |

**The rule**: if you're already on the subnet being advertised, `accept-routes=false`. You'd be telling the kernel to use a tunnel to reach a network you're already directly connected to.

### What goes wrong with `accept-routes=true` on a LAN node

```
                    ┌──── Normal (accept-routes=false) ────┐
                    │                                       │
  RPi4 ──ping──▶ ace2    ace2 ──reply──▶ RPi4              │
  172.16.1.1       172.16.1.5    via enp1s0 (direct)       │
                    │           latency: 0.2ms              │
                    └───────────────────────────────────────┘

                    ┌──── Broken (accept-routes=true) ─────┐
                    │                                       │
  RPi4 ──ping──▶ ace2    ace2 ──reply──▶ tailscale0 ──▶ RPi4
  172.16.1.1       172.16.1.5    via table 52 tunnel       │
                    │           latency: 1.7ms (hairpin)    │
                    │           inbound from other LAN      │
                    │           nodes: DROPPED (asymmetric) │
                    └───────────────────────────────────────┘
```

When ace2 has `accept-routes=true`:
1. Tailscale installs `172.16.1.0/24 dev tailscale0` in table 52
2. ip rules at priority 5270 consult table 52 before the main table
3. Reply packets to LAN hosts match table 52 → route through tunnel → RPi4
4. **Asymmetric routing**: request came in on enp1s0, reply goes out on tailscale0
5. Most networking equipment drops asymmetrically-routed packets → **LAN dies**

Outbound still works because Linux uses the connected-route (enp1s0) for locally-initiated traffic. Only replies to inbound traffic get hijacked.

## Diagnostic Commands

```bash
# Show routing tables and rules (check for table 52 hijack)
ip rule list
ip route show table 52

# Check which path the kernel picks for a LAN destination
ip route get 172.16.1.1
# Good: "dev enp1s0 src 172.16.1.5"
# Bad:  "dev tailscale0 table 52 src 100.64.0.5"

# Fix on a live node
tailscale set --accept-routes=false

# Verify: table 52 should have only 100.64.0.x entries, no 172.16.1.0/24
ip route show table 52
```

## Ansible Configuration

In provisioning playbooks, set `tailscale_accept_routes` based on node location:

```yaml
# LAN nodes (ace1, ace2, bee, jet1) — physically on 172.16.1.0/24
- role: ../roles/tailscale
  vars:
    tailscale_accept_routes: false  # Already on the subnet

# Remote nodes (VPS, workstation) — NOT on 172.16.1.0/24
- role: ../roles/tailscale
  vars:
    tailscale_accept_routes: true   # Need tunnel to reach homelab LAN
```

## Future Considerations

- If a second subnet is advertised (e.g., a remote site 10.10.0.0/24), LAN nodes CAN safely accept that route since they're not physically on it. The rule is per-subnet, not global. However, `--accept-routes` is all-or-nothing in Tailscale — there's no per-route accept. Workaround: use `ip rule add to <local-subnet> lookup main priority 100` to force local subnet through the physical interface while accepting other routes via Tailscale.
- Tailscale GitHub issues [#6231](https://github.com/tailscale/tailscale/issues/6231) and [#1227](https://github.com/tailscale/tailscale/issues/1227) track adding smarter route priority handling.
