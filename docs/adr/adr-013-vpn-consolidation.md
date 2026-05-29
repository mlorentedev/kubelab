---
id: "kubelab-adr-013-vpn-consolidation"
type: adr
status: accepted
tags: [adr, kubelab, vpn, headscale]
created: "2026-02-25"
owner: manu
---

# ADR-013: VPN Consolidation — Single Headscale Control Plane

## Status

Accepted (2026-02-25). Extends ADR-010, ADR-012.

## Context

The kubelab infrastructure currently has two separate VPN networks:

1. **Headscale** (self-hosted, `vpn.kubelab.live`) — 9 homelab nodes (workstation, VPS, K3s cluster, RPi, Beelink, Jetson). Manages mesh connectivity, split DNS, subnet routing.
2. **Tailscale SaaS** — 3+ Windows mini PCs running ts-bridge (TCP bridge for RDP access without admin privileges). Separate control plane, separate auth, no mesh visibility between the two networks.

### Problems

- **No unified view**: Two admin consoles, two sets of auth keys, two ACL policies.
- **No cross-mesh connectivity**: ts-bridge nodes on Tailscale SaaS cannot be reached from Headscale nodes (or vice versa) without manual port forwarding.
- **Contractor onboarding requires Tailscale SaaS**: Future contractor access would need yet another identity system.
- **Inconsistent identity model**: Homelab nodes authenticate to Headscale as `kubelab` user, ts-bridge nodes authenticate to Tailscale SaaS with a separate account.

### Constraints

- Corporate workstation has NO root access — cannot install native Tailscale. Uses ts-bridge as a userspace client.
- Windows mini PCs are under full control (admin/root). Run ts-bridge as server (accepting inbound RDP connections).
- Homelab nodes (K3s, RPi, etc.) require native Tailscale for kernel-level networking (subnet routing, split DNS, TUN interface).

## Decision

### Consolidate all VPN nodes under a single Headscale instance

Migrate all ts-bridge instances from Tailscale SaaS to Headscale by adding `TS_CONTROL_URL` support to ts-bridge (see ts-bridge ADR-005).

### Identity model: three Headscale users

| User | Purpose | Devices | Auth method |
|------|---------|---------|-------------|
| `kubelab` | Admin — full mesh access | workstation (native TS), corporate workstation (ts-bridge client), phone (future) | Pre-auth key |
| `work` | Windows PCs — RDP targets, implicit deny outbound | 3+ Windows mini PCs (ts-bridge server) | Pre-auth key |
| `contractors` | External access — restricted scope (future) | Contractor machines (ts-bridge client) | Pre-auth key, time-limited |

**Key principle:** The user (manu) always authenticates as `kubelab` regardless of device. The `work` user represents the Windows PCs as a device class, not a person. Contractors get a separate user for ACL isolation.

### ACL policy (file-based, Git-versioned)

Headscale ACL policy file (`policy.hujson`) with implicit deny:

```hujson
{
  // Headscale ACL Policy — kubelab VPN mesh
  // Ref: ADR-013

  "groups": {
    "group:admin":       ["kubelab"],
    "group:work":        ["work"],
    "group:contractors": ["contractors"]
  },

  "tagOwners": {
    "tag:server":  ["kubelab"],
    "tag:k3s":     ["kubelab"],
    "tag:monitor": ["kubelab"],
    "tag:gateway": ["kubelab"],
    "tag:windows": ["work"]
  },

  "acls": [
    // A: Admin (kubelab) can reach everything
    {
      "action": "accept",
      "src":    ["group:admin"],
      "dst":    ["*:*"]
    },

    // G: Contractors can ONLY reach Windows PCs on RDP port
    {
      "action": "accept",
      "src":    ["group:contractors"],
      "dst":    ["group:work:3389"]
    }

    // F: Work devices have NO outbound rules → implicit deny
    // They can be reached BY admin (rule A) but cannot initiate connections
  ],

  "ssh": [
    // Admin SSH access to all nodes
    {
      "action": "accept",
      "src":    ["group:admin"],
      "dst":    ["group:admin"],
      "users":  ["autogroup:nonroot", "root"]
    }
  ]
}
```

### Connectivity scenarios

| ID | From | To | Protocol | How |
|----|------|----|----------|-----|
| A | msi (workstation) | All homelab nodes | SSH, kubectl, HTTP | Native Tailscale → Headscale mesh |
| B | msi (workstation) | Windows PCs | RDP (3389) | Native Tailscale → ts-bridge server on Windows |
| C | Phone (future) | K3s cluster | kubectl, HTTP | Native Tailscale (Termux) → Headscale |
| D | Corporate workstation | Homelab nodes | SSH, HTTP | ts-bridge client → Headscale mesh (no root needed) |
| E | Corporate workstation | Windows PCs | RDP (3389) | ts-bridge client → ts-bridge server (both on Headscale) |
| F | Windows PCs | Anything | — | **BLOCKED** (implicit deny, isolated) |
| G | Contractors | Windows PCs only | RDP (3389) | ts-bridge client → Headscale → ts-bridge server |
| H | Admin | Headplane UI | HTTPS | headplane.kubelab.live (Authelia one-factor) |

### Headplane (admin UI)

Deploy [Headplane](https://github.com/tale/headplane) as the Headscale admin UI:

- **URL:** `headplane.kubelab.live`
- **Auth:** Authelia one-factor (PROTECTED tier per ADR-012)
- **ACL mode:** File-based (read-only in Headplane). Policy managed in Git, applied via `headscale` CLI or volume mount.
- **Deployment:** Docker container behind Traefik, same pattern as other kubelab services.

Why Headplane over headscale-ui:
- More active development (~2K stars vs ~700)
- Better UX (modern React, real-time updates)
- Full ACL editor in database mode (read-only viewer in file mode — which is what we want for IaC)
- Node management, route approval, key management from browser

### Where native Tailscale stays (cannot use ts-bridge)

| Device | Why native Tailscale required |
|--------|------------------------------|
| Homelab nodes (K3s, RPi, Bee, Jet) | Kernel TUN interface for subnet routing, split DNS, full mesh |
| Workstation (msi) | Full Tailscale features: Magic DNS, subnet routes, SSH |
| VPS | Headscale runs here + Tailscale for self-mesh |

ts-bridge is for devices where native Tailscale is impossible (no root) or unnecessary (Windows PCs only need RDP bridging).

## Implementation

### Phase 0: ts-bridge ControlURL (ts-bridge repo)

1. Add `TS_CONTROL_URL` env var to `main.go` (one-line change)
2. Update `.env.example` and bootstrap scripts
3. Test against Headscale instance
4. Release v1.3.0

### Phase 1: Headscale preparation (kubelab repo)

1. Create `work` user in Headscale
2. Create `contractors` user in Headscale (empty, for future use)
3. Write `policy.hujson` ACL file, version-control in kubelab repo
4. Configure Headscale to use file-based ACLs

### Phase 2: Headplane deployment

1. Add Headplane to Docker Compose stack (dev) and K8s manifests (staging/prod)
2. Configure IngressRoute: `headplane.kubelab.live` with Authelia one-factor
3. Connect Headplane to Headscale API socket

### Phase 3: Migrate Windows PCs

1. Update ts-bridge to v1.3.0+ on all Windows PCs
2. Set `TS_CONTROL_URL=https://vpn.kubelab.live` in `.env`
3. Generate Headscale pre-auth keys for `work` user
4. Restart ts-bridge — verify nodes appear in Headscale
5. Verify RDP connectivity from workstation via Headscale mesh

### Phase 4: Migrate corporate workstation

1. Update ts-bridge on corporate workstation
2. Set `TS_CONTROL_URL=https://vpn.kubelab.live`
3. Use `kubelab` user pre-auth key (admin access)
4. Verify connectivity to both homelab and Windows PCs

### Phase 5: Decommission Tailscale SaaS

1. Verify all nodes visible in Headscale (`headscale nodes list`)
2. Verify all connectivity scenarios (A-H)
3. Remove nodes from Tailscale SaaS console
4. Archive Tailscale SaaS account (keep dormant, do not delete)

## Rationale

### Why not replace native Tailscale with ts-bridge everywhere?

ts-bridge uses tsnet (userspace networking) — TCP only, no TUN interface, no kernel integration. Homelab nodes need:
- **Subnet routing** (RPi4 advertises 172.16.1.0/24) — requires kernel TUN
- **Split DNS** (Headscale pushes DNS config to tailscaled) — requires native daemon
- **Full protocol support** (UDP, ICMP for ping) — tsnet is TCP-only

ts-bridge fills the gap where native Tailscale is impossible, not where it's available.

### Why file-based ACLs over database ACLs?

- **IaC**: Policy file lives in Git, reviewed in PRs, auditable history.
- **Headplane**: Read-only ACL viewer prevents accidental policy changes from the UI.
- **Reproducibility**: `policy.hujson` can be applied to a fresh Headscale instance with zero manual config.

### Why three users, not one?

ACL isolation. With a single user, all nodes have equal standing. With three users:
- `kubelab` nodes get admin access (full mesh).
- `work` nodes are isolated targets (can be reached, cannot reach out).
- `contractors` get scoped access (only RDP to work devices).

This maps directly to the principle of least privilege.

## Consequences

1. **Single pane of glass**: All VPN nodes (homelab + Windows PCs + future contractors) visible in one Headscale instance + Headplane UI.
2. **Unified ACLs**: One policy file governs all access. No more split-brain.
3. **ts-bridge becomes an L3 tool**: First kubelab-adjacent project in its own repo, following the product portfolio pattern (L3: standalone, publishable without kubelab).
4. **Contractor onboarding simplified**: Generate Headscale pre-auth key for `contractors` user + distribute ts-bridge binary. No Tailscale SaaS account needed.
5. **Migration is non-destructive**: Each ts-bridge instance migrates independently. Rollback is one env var change.

## Addendum (2026-03-16): Partial Implementation — Corporate TLS Inspection

### Outcome

Phases 0-1 completed. **Phases 3-5 abandoned** due to corporate transparent TLS inspection.

Corporate networks use inline firewall TLS inspection (not a configured proxy). The firewall MITMs all TLS connections, decrypts traffic, and validates it is HTTP. Headscale serves the Tailscale Noise protocol (binary, not HTTP) after TLS handshake — the firewall detects non-HTTP content and kills the connection. This affects both native Tailscale (`tailscale up --login-server=...`) and ts-bridge (`TS_CONTROL_URL`). SSH works (different encryption, not TLS-based). Standard HTTPS to the same VPS IP works fine.

### Revised Architecture

| Device | Control Plane | Protocol | Rationale |
|--------|--------------|----------|-----------|
| Homelab nodes (K3s, RPi, etc.) | **Headscale** (`vpn.kubelab.live`) | Native Tailscale | No TLS inspection on home/VPS networks |
| Windows PCs (office) | **Tailscale SaaS** | RDP via ts-bridge | CDN relay IPs trusted by corporate firewalls |
| Corporate workstation | **Tailscale SaaS** | ts-bridge client | Same corporate network restriction |

### What stays valid

- ADR-013's identity model and ACL policy remain correct for the homelab mesh.
- `TS_CONTROL_URL` in ts-bridge is useful for non-corporate networks.
- Headscale consolidation for homelab nodes is unaffected.

### What changes

- VPN consolidation is **partial**: homelab on Headscale, corporate devices on Tailscale SaaS.
- The "single pane of glass" goal is not fully achieved — two admin consoles remain.
- Headscale migration runbooks archived to `90_archive/ts-bridge/`.
- Device inventory updated: `10_projects/ts-bridge/40-runbooks/guide-device-inventory.md`.

## Related

- [adr-010-headscale-over-tailscale-cloud](adr-010-headscale-over-tailscale-cloud.md) — Headscale as control plane
- [adr-012-environment-strategy](adr-012-environment-strategy.md) — Service distribution and domain strategy
- ts-bridge — ControlURL implementation
- ts-bridge `90-lessons.md` (2026-03-16) — Full post-mortem
