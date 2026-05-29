---
id: "kubelab-runbook-dns-homelab"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-09"
owner: manu
---

# DNS Homelab (CoreDNS + Pi-hole)

## Overview

CoreDNS runs on RPi 4 (`kubelab-rpi4`) to resolve internal DNS for `*.staging.kubelab.live` domains. Pi-hole (also on RPi 4) handles ad blocking and forwards staging queries to CoreDNS. Headscale split DNS routes only `staging.kubelab.live` to RPi 4 — prod domains resolve via public Cloudflare DNS (1.1.1.1) so they work even when RPi4 is down.

## Architecture

```
Any Tailscale node — resolves api.staging.kubelab.live or status.kubelab.live
        │
        ▼
   [1] Headscale Split DNS (config on VPS)
        "staging.kubelab.live → ask 100.64.0.10 (RPi4)"
        │
        ▼
   [2] Pi-hole on RPi4 (port 53)
        Receives query, matches dnsmasq conditional forward
        "kubelab.live → forward to 172.17.0.1:5353 (Docker bridge → host:5353)"
        │
        ▼
   [3] CoreDNS on RPi4 (port 5353)
        Zone: staging.kubelab.live → 100.64.0.4 (K3s Traefik)
        Zone: kubelab.live → bare-metal services (status, ollama, jetson)
        Fallback: forward to 1.1.1.1 / 8.8.8.8
        │
        ▼
   K3s Traefik Ingress routes by Host header → correct pod
   OR bare-metal service directly via Tailscale IP
```

**Why 3 layers?**
- **Headscale split DNS**: Tells all VPN clients where to ask (without this, they'd ask 1.1.1.1 which doesn't know internal domains)
- **Pi-hole**: Already owns port 53 on RPi4. Provides ad blocking + conditional forward
- **CoreDNS**: Holds the actual DNS records. Separated from Pi-hole so it can be the permanent DNS solution (Pi-hole is removable)

## Ingress IP Reference

| Environment | Domain pattern | Resolves to | How |
|-------------|---------------|-------------|-----|
| **Production (all clients)** | `*.kubelab.live` | `162.55.57.175` (public VPS IP) | Cloudflare DNS via global resolvers (1.1.1.1) — works with RPi4 off |
| **Staging (VPN only)** | `*.staging.kubelab.live` | `100.64.0.4` (k3s-server Tailscale IP) | Headscale split DNS → RPi4 CoreDNS (requires RPi4 up) |
| **Local dev** | `*.kubelab.test` | `127.0.0.1` | `/etc/hosts` |

`100.64.0.4` is the staging equivalent of `162.55.57.175` in prod. Both point to Traefik (ingress), which routes by Host header to the correct app.

## Prerequisites

- RPi 4 running with Tailscale (`100.64.0.10`) → see [headscale-setup](headscale-setup.md)
- Pi-hole running on RPi 4 (port 53) → see [pihole-setup](pihole-setup.md)
- Docker installed on RPi 4
- K3s cluster operational with Traefik ingress → see [k3s-setup](k3s-setup.md)
- Headscale control plane on VPS → see [headscale-setup](headscale-setup.md)

## Deployment

### 1. Deploy CoreDNS + Pi-hole on RPi 4

Both services are defined in `edge/dns-gateway/compose.base.yml`:

```bash
# From workstation — copy all config files
scp edge/dns-gateway/Corefile edge/dns-gateway/compose.base.yml edge/dns-gateway/pihole-forwarding.conf manu@100.64.0.10:~/coredns/

# On RPi 4
ssh manu@100.64.0.10
cd ~/coredns
docker compose -f compose.base.yml up -d
```

**Port mapping**:
- Pi-hole: port 53 (DNS) + port 80 (admin UI)
- CoreDNS: port 5353 (avoids conflict with Pi-hole on 53)

> **Avahi conflict**: Ubuntu's `avahi-daemon` also uses port 5353 (mDNS).
> Disable it — not needed on a headless server:
> ```bash
> sudo systemctl disable --now avahi-daemon avahi-daemon.socket
> ```

### 2. Pi-hole configuration

Pi-hole v6 uses FTL (not dnsmasq) as its DNS resolver. Custom dnsmasq config files require explicit opt-in.

```bash
# Enable dnsmasq.d config loading in Pi-hole v6
docker exec pihole sed -i 's/etc_dnsmasq_d = false/etc_dnsmasq_d = true/' /etc/pihole/pihole.toml

# Restart Pi-hole to load changes
docker restart pihole
```

The `pihole-forwarding.conf` is automatically mounted via the compose file. No manual file copying needed.

> **Critical gotchas:**
> - `pihole reloaddns` does NOT reload dnsmasq config files. Use `docker restart pihole`.
> - Inside the Pi-hole container, `127.0.0.1` is the container itself, NOT the host. Use `172.17.0.1` (Docker bridge gateway) to reach CoreDNS on host port 5353.
> - `etc_dnsmasq_d` must be `true` in pihole.toml or forwarding configs are ignored.

### 3. Configure Headscale split DNS (on VPS)

Edit `/opt/headscale/config/config.yaml` on VPS:

```yaml
dns:
  magic_dns: true
  base_domain: kubelab.internal  # ADR-025: IANA-reserved .internal TLD
  override_local_dns: true
  nameservers:
    global:
      - 1.1.1.1
      - 1.0.0.1
    split:
      staging.kubelab.live:
        - 100.64.0.10      # RPi4 Pi-hole (port 53) → CoreDNS (port 5353)
  search_domains: []
  extra_records: []
```

> **Important:** Split DNS targets `staging.kubelab.live` (NOT `kubelab.live`). Prod domains have public Cloudflare records and must resolve via global DNS (1.1.1.1) so they work when RPi4 is down. Changed 2026-03-03 — previously `kubelab.live` caused total DNS failure for prod domains when RPi4 was off.

Restart Headscale:
```bash
cd /opt/headscale && sudo docker compose restart headscale
```

After restart, Tailscale clients must re-sync DNS. Force it:
```bash
sudo tailscale down && sudo tailscale up --login-server=https://vpn.kubelab.live --accept-routes
```

### 4. Accept routes on workstation

Tailscale clients need `--accept-routes` to use the subnet router:

```bash
# On workstation
sudo tailscale up --login-server=https://vpn.kubelab.live --accept-routes
```

## Corefile Reference

`edge/dns-gateway/Corefile` in the repo:

```
staging.kubelab.live {
    hosts {
        100.64.0.4 staging.kubelab.live
        100.64.0.4 api.staging.kubelab.live
        100.64.0.4 web.staging.kubelab.live
        100.64.0.4 blog.staging.kubelab.live
        100.64.0.4 grafana.staging.kubelab.live
        100.64.0.4 traefik.staging.kubelab.live
        100.64.0.4 auth.staging.kubelab.live
        100.64.0.4 status.staging.kubelab.live
        100.64.0.4 gitea.staging.kubelab.live
        100.64.0.4 n8n.staging.kubelab.live
        100.64.0.4 minio.staging.kubelab.live
        100.64.0.4 console.minio.staging.kubelab.live
        100.64.0.4 loki.staging.kubelab.live
        100.64.0.4 portainer.staging.kubelab.live
        fallthrough
    }
    template IN A staging.kubelab.live {
        match .*\.staging\.kubelab\.live
        answer "{{ .Name }} 60 IN A 100.64.0.4"
        fallthrough
    }
    log
    errors
}

kubelab.live {
    hosts {
        # Bare-metal services: individual Tailscale IPs
        100.64.0.6 status.kubelab.live       # RPi3
        100.64.0.3 ollama.kubelab.live       # Beelink
        100.64.0.8 jetson.kubelab.live       # Jetson Nano
        # K3s prod services: VPS Tailscale IP
        100.64.0.2 kubelab.live
        100.64.0.2 api.kubelab.live
        100.64.0.2 web.kubelab.live
        100.64.0.2 blog.kubelab.live
        100.64.0.2 auth.kubelab.live
        100.64.0.2 grafana.kubelab.live
        100.64.0.2 loki.kubelab.live
        100.64.0.2 gitea.kubelab.live
        100.64.0.2 n8n.kubelab.live
        100.64.0.2 minio.kubelab.live
        100.64.0.2 console.minio.kubelab.live
        # Headscale MUST use public IP — bootstrap dependency (nodes need VPN to reach Tailscale IPs)
        # networking.vps.public_ip (common.yaml)
        162.55.57.175 vpn.kubelab.live
        fallthrough
    }
    forward . 1.1.1.1 8.8.8.8
    log
    errors
}

. {
    forward . 1.1.1.1 8.8.8.8
    cache 30
    log
    errors
}
```

**Zone precedence**: CoreDNS matches the most specific zone first. `staging.kubelab.live` takes priority over `kubelab.live` for staging queries.

**Critical**: The `kubelab.live` zone uses explicit `hosts` entries only (NO template wildcard). CoreDNS `template` overrides `hosts` when both are in the same zone with different IPs — see lesson `[2026-03-01] CoreDNS template Overrides hosts`. The staging zone's template wildcard is safe because all IPs are identical (`100.64.0.4`).

**To add a new service**:
- Staging (K3s): Rely on the wildcard template (catches all `*.staging.kubelab.live`)
- Prod (K3s on VPS): Add explicit entry in `kubelab.live` hosts block (`100.64.0.2 <service>.kubelab.live`)
- Bare-metal: Add explicit entry in `kubelab.live` hosts block with the specific Tailscale IP
- After editing: `make deploy-dns` to push to RPi4

**Deployment to RPi4** (semi-automated via Makefile):
```bash
make deploy-dns   # SCP + restart CoreDNS on RPi4 via SSH
```

## Verification

```bash
# 1. CoreDNS direct (from RPi4)
dig @127.0.0.1 -p 5353 api.staging.kubelab.live +short
# → 100.64.0.4

# 2. Bare-metal service (from RPi4)
dig @127.0.0.1 -p 5353 status.kubelab.live +short
# → 100.64.0.6

# 3. Pi-hole chain (from RPi4, port 53 → CoreDNS 5353)
dig @127.0.0.1 status.kubelab.live +short
# → 100.64.0.6

# 4. From workstation (full chain: Headscale → Pi-hole → CoreDNS)
dig status.kubelab.live +short
# → 100.64.0.6
dig api.staging.kubelab.live +short
# → 100.64.0.4

# 5. Public domains still resolve (forward works)
dig @127.0.0.1 -p 5353 google.com +short
# → Google IPs

# 6. Public kubelab.live domains fall through correctly
dig vpn.kubelab.live +short
# → VPS public IP (via Cloudflare)
```

## Troubleshooting

### CoreDNS unhealthy

The default CoreDNS Docker image does not include `dig`. The healthcheck uses `dig` which fails. This is cosmetic — CoreDNS still works. Fix by using a wget-based healthcheck or ignoring the status.

### Port 5353 already in use

```bash
sudo ss -ulnp | grep 5353
```

If `avahi-daemon`: disable it (`sudo systemctl disable --now avahi-daemon avahi-daemon.socket`).

### Pi-hole not forwarding to CoreDNS

1. Check `etc_dnsmasq_d = true` in pihole.toml:
   ```bash
   docker exec pihole grep etc_dnsmasq_d /etc/pihole/pihole.toml
   ```
2. Check forwarding file is mounted:
   ```bash
   docker exec pihole cat /etc/dnsmasq.d/pihole-forwarding.conf
   # → server=/kubelab.live/172.17.0.1#5353
   ```
3. **Restart Pi-hole** (reloaddns is NOT enough for dnsmasq config changes):
   ```bash
   docker restart pihole
   ```

### Headscale split DNS not reaching clients

Tailscale clients cache DNS config. Force re-sync:
```bash
sudo tailscale down && sudo tailscale up --login-server=https://vpn.kubelab.live --accept-routes
```

### RPi4 Tailscale bootstrap circular dependency after reboot

**Symptom**: RPi4 Tailscale stuck in `unexpected state: NoState`. Error: `fetch control key: Get "https://vpn.kubelab.live/key": dial tcp 100.64.0.2:443: connection timed out`.

**Root cause**: Circular dependency — RPi4 resolves `vpn.kubelab.live` via its own CoreDNS → Tailscale IP (`100.64.0.2`) → needs Tailscale to be up → can't connect.

**Automatic fix** (already deployed):
1. **Corefile**: `vpn.kubelab.live` resolves to public IP `162.55.57.175` (not Tailscale IP)
2. **`/etc/hosts` on RPi4**: `162.55.57.175 vpn.kubelab.live` as permanent fallback
3. **Systemd watchdog**: `tailscale-watchdog.timer` auto-reconnects every 5 min

**Manual fix** (if all else fails):
```bash
# SSH to RPi4 via LAN (172.16.1.1)
echo "162.55.57.175 vpn.kubelab.live" | sudo tee -a /etc/hosts
sudo tailscale up --login-server=https://vpn.kubelab.live --accept-dns=false --advertise-routes=172.16.1.0/24
# After connected, remove temporary entry (if not using permanent /etc/hosts)
sudo sed -i '/162.55.57.175 vpn.kubelab.live/d' /etc/hosts
```

**RPi4 Tailscale flags** (must be passed every time, non-default):
- `--login-server=https://vpn.kubelab.live` — self-hosted Headscale
- `--accept-dns=false` — RPi4 runs its own DNS (Pi-hole), don't let Tailscale override
- `--advertise-routes=172.16.1.0/24` — RPi4 is subnet router for LAN

## Persistence checklist

All changes below survive reboot:

| Component | Persistence | How |
|-----------|------------|-----|
| CoreDNS container | `restart: unless-stopped` in compose | Docker auto-starts |
| CoreDNS config | Bind mount `~/coredns/Corefile` from repo | File on disk |
| Pi-hole container | `restart: unless-stopped` in compose | Docker auto-starts |
| Pi-hole forwarding | Bind mount `pihole-forwarding.conf` from repo | Always in sync |
| Pi-hole `etc_dnsmasq_d=true` | In `pihole.toml` (Docker volume `pihole_data`) | Persists across restarts |
| Avahi disabled | `systemctl disable` | Survives reboot |
| Headscale split DNS | In `/opt/headscale/config/config.yaml` | File on disk |
| RPi4 `--accept-dns=false` | Tailscale remembers flags | Persists across restarts |
| RPi4 resolv.conf | `chattr +i` protected | Immutable |
| RPi4 `/etc/hosts` vpn entry | `162.55.57.175 vpn.kubelab.live` | Bootstrap fallback |
| RPi4 Tailscale watchdog | `tailscale-watchdog.timer` (systemd, enabled) | Auto-reconnects every 5 min |

## Files in repo

| File | Purpose |
|------|---------|
| `edge/dns-gateway/Corefile` | CoreDNS zone config (staging + bare-metal) |
| `edge/dns-gateway/compose.base.yml` | Pi-hole + CoreDNS deployment |
| `edge/dns-gateway/pihole-forwarding.conf` | dnsmasq forwarding rule (kubelab.live → CoreDNS) |

## DNS Resilience — /etc/hosts Fallback via Ansible

### Problem

All LAN nodes depend on Pi-hole (RPi4) for DNS. If RPi4 goes down:
1. DNS fails for all LAN nodes
2. Nodes can't resolve `vpn.kubelab.live` (Headscale control server)
3. Tailscale can't reconnect → nodes become VPN-unreachable
4. Cascade failure: one node down → entire mesh degraded

### Solution

Ansible role `dns_resilience` manages a block in `/etc/hosts` on **all homelab nodes** with the VPS public IP for `vpn.kubelab.live`. This bypasses the DNS chain entirely for the most critical domain.

```
# In /etc/hosts on every node (managed by Ansible):
# BEGIN KUBELAB DNS RESILIENCE (managed by Ansible)
162.55.57.175 vpn.kubelab.live
# END KUBELAB DNS RESILIENCE (managed by Ansible)
```

### Files in repo

| File | Purpose |
|------|---------|
| `infra/ansible/inventories/homelab.yml` | Static inventory — 7 nodes, Tailscale IPs |
| `infra/ansible/roles/dns_resilience/tasks/main.yml` | Role: `blockinfile` for normal nodes, `raw` for legacy Python (Jetson) |
| `infra/ansible/playbooks/homelab-dns.yml` | Playbook applying the role to all nodes |

### Inventory

Uses **Tailscale IPs** (run from workstation with Tailscale). Two groups:

- `lan_nodes`: jet1, bee, k3s-server, k3s-agent-1, k3s-agent-2
- `gateway_nodes`: rpi4, rpi3

Jetson Nano has `legacy_python: true` (Ubuntu 18.04 / Python 3.6 — Ansible modules don't work, uses `raw` instead).

### Execution

```bash
cd infra/ansible

# Dry-run (see what would change)
ansible-playbook -i inventories/homelab.yml playbooks/homelab-dns.yml -K --check --diff

# Apply to all nodes (-K prompts for sudo password)
ansible-playbook -i inventories/homelab.yml playbooks/homelab-dns.yml -K

# Verify specific node
ansible -i inventories/homelab.yml kubelab-jet1 -m raw -a "grep vpn.kubelab.live /etc/hosts"

# Idempotency: second run should show 0 changed
ansible-playbook -i inventories/homelab.yml playbooks/homelab-dns.yml -K
```

> **`-K` required**: Most nodes need sudo password for `/etc/hosts`. RPi3 has NOPASSWD.
> If a node is already disconnected from Tailscale, fix it manually via SSH LAN first
> (`ssh <host>-lan`), then run this playbook to prevent recurrence.

### What this guarantees on full homelab restart

1. VPS (Headscale) is external — doesn't restart with your homelab
2. Each node boots → reads `/etc/hosts` → resolves `vpn.kubelab.live` → Tailscale reconnects
3. **Does NOT depend on RPi4 booting first** — that was the failure chain this breaks
4. Only scenario NOT covered: VPS IP changes (extraordinary event, would also require DNS update)

### Extending

Add more critical domains to the `block:` in `roles/dns_resilience/tasks/main.yml`:

```yaml
block: |
  {{ headscale_ip }} {{ headscale_domain }}
  # Future: add more critical entries here
  # 100.64.0.5 pihole.kubelab.live
```

### Toolkit integration (future)

Currently a standalone playbook — no toolkit wrapper needed. If more homelab-wide playbooks accumulate (3+), consider a `toolkit infra homelab` subcommand that discovers and runs playbooks from `infra/ansible/playbooks/`.

### Last tested

2026-02-22: Applied to 7/7 nodes. Idempotency verified (second run: 0 changed). Jetson `raw` path works. All nodes resolve `vpn.kubelab.live` → `162.55.57.175` via `/etc/hosts`.

## Related

- [headscale-setup](headscale-setup.md) — VPN mesh setup (split DNS in Phase 6)
- [pihole-setup](pihole-setup.md) — Pi-hole deployment on RPi 4
- [k3s-setup](k3s-setup.md) — K3s cluster setup
- `edge/dns-gateway/` — DNS configuration files in repo

## Last tested

2026-02-21: Full chain verified. CoreDNS on port 5353, Pi-hole forwarding via compose bind mount, Headscale split DNS for `kubelab.live`.
2026-03-03: Narrowed split DNS from `kubelab.live` → `staging.kubelab.live`. Prod domains now resolve via public Cloudflare DNS regardless of RPi4 state. Verified `status.kubelab.live` resolves via 1.1.1.1 from VPN clients.
2026-02-22: DNS resilience playbook applied to all 7 nodes. `/etc/hosts` entries verified.
2026-03-01: Corefile updated with gitea/n8n/minio/loki staging entries. Prod zone uses explicit hosts (removed template wildcard — it overrode hosts entries). Deployed to RPi4 via `make deploy-dns`. All bare-metal IPs verified correct.
2026-03-01: Fixed Tailscale bootstrap circular dependency. `vpn.kubelab.live` now resolves to public IP `162.55.57.175` in Corefile. RPi4 has permanent `/etc/hosts` fallback + `tailscale-watchdog.timer` (5-min auto-reconnect). Uptime Kuma proxied through K3s Traefik as external service.
