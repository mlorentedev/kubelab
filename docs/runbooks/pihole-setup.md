---
id: "kubelab-runbook-pihole-setup"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-10"
owner: manu
---

# Pi-hole Setup

## Overview

Pi-hole deployed as Docker container on RPi 4 (`kubelab-rpi4`) for network-wide DNS sinkhole (ad blocking + telemetry blocking). Pi-hole handles **DNS only** — dnsmasq continues to handle **DHCP separately**.

> **Architecture decision**: Pi-hole runs alongside dnsmasq, NOT replacing it. dnsmasq handles DHCP (port 67), Pi-hole handles DNS (port 53). This separation of concerns means a Pi-hole failure doesn't kill DHCP, and vice versa.

## Prerequisites

- RPi 4 provisioned with Ubuntu Server 24.04 LTS — see [hardware-setup](hardware-setup.md)
- Docker installed on RPi 4
- dnsmasq running for DHCP only (port 67, no DNS on port 53)
- SSH access: `ssh rpi4`

## Steps

### 1. Disable systemd-resolved

Ubuntu's `systemd-resolved` binds port 53 and must be removed completely for Pi-hole to take over DNS.

```bash
ssh rpi4

# Check what's using port 53
sudo ss -tlnp | grep :53
sudo ss -ulnp | grep :53
# systemd-resolved will show on 127.0.0.53:53 and 127.0.0.54:53

# Disable and stop
sudo systemctl stop systemd-resolved
sudo systemctl disable systemd-resolved

# Replace the symlinked resolv.conf with a static one
sudo rm /etc/resolv.conf
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
```

> **Why disable entirely instead of just the stub listener?** We tried `DNSStubListener=no` approach but it's fragile — resolved can still grab port 53 after updates. Full disable is cleaner when Pi-hole will handle all DNS.
>
> **Is this robust?** Yes. systemd-resolved is a convenience layer for desktop systems. On a headless server acting as a DNS gateway, Pi-hole replaces its function entirely. The static `/etc/resolv.conf` ensures the host itself can still resolve names (via 8.8.8.8 as fallback, later pointed to Pi-hole itself).

### 2. Deploy Pi-hole container

Compose file lives in repo: `infra/stacks/services/core/pihole/compose.yml`.
Deployed to RPi 4 at `/opt/pihole/`.

```bash
# Copy compose to RPi 4
scp infra/stacks/services/core/pihole/compose.yml rpi4:/opt/pihole/

# Create .env with password
ssh rpi4 'echo "PIHOLE_WEBPASSWORD=<your-password>" > /opt/pihole/.env'

# Deploy
ssh rpi4 "cd /opt/pihole && docker compose up -d"
```

**Design decisions:**
- `restart: unless-stopped`: survives reboots, but can be manually stopped
- Named Docker volumes (`pihole_data`, `pihole_dnsmasq`) as `external: true`: reuses existing volumes
- Port 80 mapped for web admin UI
- NOT using `network_mode: host` — DHCP stays with dnsmasq, Pi-hole only needs DNS ports
- Password in `.env` file (gitignored), not in compose

> **Volume gotcha (2026-02-21)**: Docker Compose prefixes volume names with the project name
> (directory). If volumes are NOT marked `external: true`, compose creates NEW empty volumes
> (`pihole_pihole_data`) instead of reusing the originals (`pihole_data`). This causes DNS to
> fail because Pi-hole starts with empty config. Always use `external: true` when migrating
> from `docker run` to compose with existing named volumes.

### 3. Configure listening mode for LAN access

Pi-hole v6 defaults to `listeningMode = "LOCAL"` which only accepts queries from networks local to the container (Docker bridge `172.17.0.0/16`). Our LAN queries come from `172.16.1.0/24` which Pi-hole considers "non-local".

```bash
# Check current mode
sudo docker exec pihole bash -c 'grep "listeningMode" /etc/pihole/pihole.toml'
# Output: listeningMode = "LOCAL"

# Change to ALL to accept queries from any source
sudo docker exec pihole bash -c "sed -i 's/listeningMode = \"LOCAL\"/listeningMode = \"ALL\"/' /etc/pihole/pihole.toml"
sudo docker restart pihole
```

> **Is `listeningMode = ALL` secure?** In our setup, yes. Pi-hole is behind the RPi 4 gateway — only devices on the KubeLab LAN (172.16.1.0/24) and the home router network (10.0.0.0/24) can reach port 53. It's not exposed to the internet. If concerned, use `BIND` mode with a specific interface instead.
>
> **Gotcha**: Pi-hole v6 changed the CLI significantly. `pihole -a interface all` no longer works. Must edit `/etc/pihole/pihole.toml` directly. The log message `WARNING: dnsmasq: ignoring query from non-local network 172.16.1.2` is the indicator this needs fixing.

### 4. Verify

```bash
# From RPi 4 itself
dig @127.0.0.1 google.com +short
# Should return IP addresses

# From any LAN device (e.g., ace1)
dig @172.16.1.1 google.com +short
# Should return IP addresses

# Ad blocking works
dig @172.16.1.1 ads.google.com +short
# Should return 0.0.0.0

# Container is healthy
sudo docker ps | grep pihole
# Should show (healthy)
```

### 5. Configure LAN devices to use Pi-hole (optional)

For KubeLab LAN devices, update their DNS to point to Pi-hole:

```bash
# In each VM's /etc/network/interfaces, change:
dns-nameservers 172.16.1.1 8.8.8.8
# (Pi-hole first, public DNS as fallback)
```

Or configure dnsmasq on RPi 4 to advertise Pi-hole as DNS via DHCP:

```bash
# Add to /etc/dnsmasq.d/kubelab-dhcp.conf on RPi 4:
dhcp-option=6,172.16.1.1
```

### 6. Configure home router DNS (optional — PIHOLE-003)

To get Pi-hole filtering for all home devices (not just KubeLab LAN):

1. Log into home router admin panel
2. Set primary DNS to: `10.0.0.131` (RPi 4 WAN IP)
3. Set secondary DNS to: `8.8.8.8` (fallback)

## Web Admin UI

Access Pi-hole dashboard from workstation via SSH tunnel:

```bash
ssh -L 8080:172.16.1.1:80 rpi4 -N
# Then open http://localhost:8080/admin
```

## Troubleshooting

**Port 53 already in use:**
- `systemd-resolved` is the usual culprit on Ubuntu
- Check: `sudo ss -ulnp | grep :53`
- Fix: disable systemd-resolved entirely (see Step 1)

**"ignoring query from non-local network" in logs:**
- Pi-hole's `listeningMode` is set to `LOCAL` (default in v6)
- Fix: change to `ALL` in `/etc/pihole/pihole.toml` (see Step 3)
- This is expected when Pi-hole runs in Docker bridge mode and LAN traffic arrives via DNAT

**Pi-hole CLI commands changed in v6:**
- `pihole -a interface all` → no longer works
- `pihole -a -p` → use `WEBPASSWORD` env var or edit toml directly
- Always check `/etc/pihole/pihole.toml` for configuration

**Container starts but DNS doesn't resolve:**
- Check logs: `sudo docker logs pihole --tail 30`
- Verify port mapping: `sudo docker ps` should show `0.0.0.0:53->53/udp`
- Verify no port conflicts: `sudo ss -ulnp | grep :53`

## Coexistence with dnsmasq

Pi-hole and dnsmasq run side by side on RPi 4:

| Service | Port | Function |
|---------|------|----------|
| dnsmasq (standalone) | 67/UDP | DHCP only |
| Pi-hole (Docker) | 53/TCP+UDP | DNS only |
| Pi-hole (Docker) | 80/TCP | Web admin UI |

dnsmasq was configured with `port=0` implicitly (no `port` directive = no DNS). If dnsmasq ever starts listening on port 53, Pi-hole will fail to bind. Check with `sudo ss -ulnp | grep :53`.

## Rollback

```bash
# Stop Pi-hole (compose)
ssh rpi4 "cd /opt/pihole && docker compose down"

# Or if still using docker run:
# sudo docker stop pihole && sudo docker rm pihole

# Re-enable systemd-resolved
sudo systemctl enable systemd-resolved
sudo systemctl start systemd-resolved
sudo rm /etc/resolv.conf
sudo ln -s /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
```

## Related

- [hardware-setup](hardware-setup.md) — RPi 4 provisioning and gateway setup
- [headscale-setup](headscale-setup.md) — VPN mesh (Tailscale clients will use Pi-hole for DNS)

## Last tested

- 2026-02-19: Pi-hole deployed on kubelab-rpi4 via Docker. systemd-resolved disabled. listeningMode changed from LOCAL to ALL for LAN access. Verified: DNS resolution from RPi 4 localhost + LAN devices (ace1). Ad blocking confirmed (ads.google.com → 0.0.0.0). dnsmasq DHCP continues to work independently on port 67.
- 2026-02-21: Migrated from `docker run` to Docker Compose (`/opt/pihole/compose.yml`). Volumes marked `external: true` to reuse existing data. Compose file in repo at `infra/stacks/services/core/pihole/`.
