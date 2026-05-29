---
id: "kubelab-runbook-monitoring"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-08"
owner: manu
---

# Monitoring

## Overview

Monitor KubeLab container performance, review Traefik access logs, check health endpoints, and set up basic container alerts.

## Prerequisites

- Docker running with KubeLab containers active
- SSH access to the server
- `curl`, `jq` available

## Steps

### 1. View service logs (preferred: toolkit)

```bash
# View logs with toolkit (preferred method)
toolkit services logs traefik
toolkit services logs api
toolkit services logs web

# View logs without following
toolkit services logs traefik --no-follow
```

### 2. Verify performance metrics

```bash
# CPU and memory per container
docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"

# Disk usage on the deployment host
df -h /
du -sh /var/lib/docker/

# Processes in a container
docker exec $(docker ps -q -f name=api) ps aux
```

### 3. Traefik access logs

```bash
# View latest accesses (via toolkit)
toolkit services logs traefik --no-follow

# View latest accesses (raw Docker fallback)
docker logs $(docker ps -q -f name=traefik) | tail -50

# Filter 4xx/5xx errors
docker logs $(docker ps -q -f name=traefik) 2>&1 | grep -E "(4[0-9]{2}|5[0-9]{2})"

# Follow logs in real time
docker logs $(docker ps -q -f name=traefik) -f
```

### 4. Health endpoints

```bash
# Quick verification script
check_endpoints() {
  endpoints=(
    "https://mlorente.dev"
    "https://blog.kubelab.live"
    "https://api.kubelab.live/health"
  )

  for endpoint in "${endpoints[@]}"; do
    if curl -f -s "$endpoint" > /dev/null; then
      echo "OK $endpoint"
    else
      echo "FAIL $endpoint"
    fi
  done
}

check_endpoints
```

### 5. Basic container alerts

```bash
#!/bin/bash
# monitor-containers.sh

containers=("traefik" "web" "blog" "api")

for container in "${containers[@]}"; do
  if ! docker ps | grep -q "$container"; then
    echo "ALERT: Container $container is not running"
    # Add webhook or email notification here
  fi
done
```

### 6. External monitoring (RPi 3)

A separate Uptime Kuma instance runs on RPi 3 (`kubelab-rpi3`), physically separate from the homelab.
It connects directly to the router (independent internet path), outside the RPi 4 gateway blast radius.
Monitors both staging (via Tailscale) and production (public URLs).

```bash
# RPi 3 access (via Tailscale)
# Uptime Kuma UI: http://100.64.0.6:3001
# Compose file (source of truth): infra/stacks/services/observability/uptime/compose.yml
```

#### RPi3 initial setup / reprovisioning

If RPi3 needs to be rebuilt from scratch:

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker manu

# 2. Install CA certificates (required for HTTPS monitors)
sudo apt update && sudo apt install -y ca-certificates
sudo update-ca-certificates

# 3. Install Tailscale and join the network
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --login-server https://vpn.kubelab.live

# 4. Deploy Uptime Kuma
mkdir -p ~/uptime-kuma
# Copy compose.yml from repo (from workstation):
# scp infra/stacks/services/observability/uptime/compose.yml manu@100.64.0.6:~/uptime-kuma/
cd ~/uptime-kuma && docker compose up -d

# 5. Restore monitors from backup (from workstation):
# toolkit monitoring restore
```

**Key detail**: The compose.yml includes `dns: [100.64.0.10, 1.1.1.1]` so the container
can resolve `*.staging.kubelab.live` via Pi-hole. Without this, staging monitors fail
with `getaddrinfo ENOTFOUND`.

#### How to add monitors in Uptime Kuma

1. Open UI: `http://100.64.0.6:3001`
2. Click **Add New Monitor**
3. Select type (HTTP(s), Ping, TCP Port)
4. Fill in target, interval, retries (3), retry interval (30s)
5. Assign to a **Group** (create group first via Status Pages or tags)
6. For HTTPS monitors: enable **Ignore TLS/SSL Error** for staging (self-signed certs may appear)

**Tip — dual LAN + Tailscale monitoring**: Create two ping monitors per node (one LAN, one Tailscale). If LAN fails but Tailscale works → the node is alive but RPi4 gateway/NAT is broken. This gives instant root cause diagnosis.

#### Tags

Create these tags first (**Settings** → **Tags** or inline when adding monitors):

| Tag | Color | Meaning |
|-----|-------|---------|
| `lan` | #e74c3c (red) | Reachable via LAN 172.16.1.x |
| `tailscale` | #3498db (blue) | Reachable via VPN 100.64.0.x |
| `public` | #2ecc71 (green) | Reachable from public internet |
| `k3s` | #9b59b6 (purple) | K3s cluster node |
| `proxmox` | #e67e22 (orange) | Proxmox hypervisor |
| `app` | #1abc9c (cyan) | Application/service endpoint |

#### Status Page: `kubelab` (slug: kubelab)

All infrastructure and application monitors. 5 groups inside.

#### Group: K3s Cluster

| Friendly Name | Type | Target | Interval | Tags |
|---|---|---|---|---|
| k3s-server LAN | Ping | `172.16.1.10` | 60 | `lan`, `k3s` |
| k3s-server Tailscale | Ping | `100.64.0.4` | 60 | `tailscale`, `k3s` |
| k3s-agent-1 LAN | Ping | `172.16.1.11` | 60 | `lan`, `k3s` |
| k3s-agent-1 Tailscale | Ping | `100.64.0.7` | 60 | `tailscale`, `k3s` |
| k3s-agent-2 LAN | Ping | `172.16.1.12` | 60 | `lan`, `k3s` |
| k3s-agent-2 Tailscale | Ping | `100.64.0.9` | 60 | `tailscale`, `k3s` |

#### Group: Proxmox Hosts

Accept Self-Signed Certificate = ON for Proxmox UI monitors.

| Friendly Name | Type | Target | Interval | Tags |
|---|---|---|---|---|
| Acemagic-1 LAN | Ping | `172.16.1.2` | 60 | `lan`, `proxmox` |
| Acemagic-1 Proxmox UI | HTTP(s) | `https://172.16.1.2:8006` | 300 | `lan`, `proxmox` |
| Acemagic-2 LAN | Ping | `172.16.1.5` | 60 | `lan`, `proxmox` |
| Acemagic-2 Proxmox UI | HTTP(s) | `https://172.16.1.5:8006` | 300 | `lan`, `proxmox` |

#### Group: Gateway & Network

| Friendly Name | Type | Target | Interval | Tags |
|---|---|---|---|---|
| RPi4 LAN | Ping | `172.16.1.1` | 60 | `lan` |
| RPi4 Tailscale | Ping | `100.64.0.10` | 60 | `tailscale` |
| Pi-hole Admin | HTTP | `http://172.16.1.1/admin` | 120 | `lan`, `app` |
| RPi3 Tailscale | Ping | `100.64.0.6` | 120 | `tailscale` |

#### Group: Infrastructure

| Friendly Name | Type | Target | Interval | Tags |
|---|---|---|---|---|
| VPS Tailscale | Ping | `100.64.0.2` | 60 | `tailscale` |
| VPS SSH | TCP Port | `162.55.57.175:22` | 120 | `public` |
| Beelink LAN | Ping | `172.16.1.3` | 120 | `lan` |
| Beelink Tailscale | Ping | `100.64.0.3` | 120 | `tailscale` |
| Beelink Ollama API | HTTP | `http://100.64.0.3:11434/api/tags` | 300 | `tailscale`, `app` |
| Jetson LAN | Ping | `172.16.1.4` | 120 | `lan` |
| Jetson Tailscale | Ping | `100.64.0.8` | 120 | `tailscale` |
| Headscale | HTTP(s) | `https://vpn.kubelab.live/health` | 120 | `public`, `app` |

#### Group: Staging Apps

Accept Self-Signed Certificate = ON if TLS errors.

| Friendly Name | Type | Target | Interval | Tags |
|---|---|---|---|---|
| Staging Web | HTTP(s) | `https://web.staging.kubelab.live` | 60 | `tailscale`, `app` |
| Staging API | HTTP(s) | `https://api.staging.kubelab.live/health` | 60 | `tailscale`, `app` |
| Staging Blog | HTTP(s) | `https://blog.staging.kubelab.live` | 60 | `tailscale`, `app` |
| Staging Grafana | HTTP(s) | `https://grafana.staging.kubelab.live/api/health` | 120 | `tailscale`, `app` |

#### Group: Production Apps

| Friendly Name | Type | Target | Interval | Tags |
|---|---|---|---|---|
| Prod Web | HTTP(s) | `https://mlorente.dev` | 60 | `public`, `app` |
| Prod API | HTTP(s) | `https://api.kubelab.live/health` | 60 | `public`, `app` |
| Prod Blog | HTTP(s) | `https://blog.kubelab.live` | 60 | `public`, `app` |

#### Status Page: `home` (slug: home)

Home network devices, separate from kubelab infrastructure.

| Friendly Name | Type | Target | Interval | Tags |
|---|---|---|---|---|
| Router | Ping | `10.0.0.1` | 60 | `lan` |
| Smart Plug | Ping | IP TBD | 120 | `lan` |

**Total: 33 monitors** across both status pages.

#### LAN IP reference (172.16.1.0/24)

| IP | Host | Role |
|----|------|------|
| .1 | kubelab-rpi4 | Gateway, Pi-hole, CoreDNS |
| .2 | kubelab-ace1 | Proxmox (k3s-server + k3s-agent-1 VMs) |
| .3 | kubelab-bee | Beelink, Ollama bare metal |
| .4 | kubelab-jet1 | Jetson Nano, Pollex |
| .5 | kubelab-ace2 | Proxmox (k3s-agent-2 VM) |
| .10 | k3s-server | K3s control plane (VM on ace1) |
| .11 | k3s-agent-1 | K3s worker (VM on ace1) |
| .12 | k3s-agent-2 | K3s worker (VM on ace2) |

#### Tailscale IP reference (100.64.0.0/24)

| IP | Host |
|----|------|
| .1 | msi (workstation) |
| .2 | kubelab-vps |
| .3 | kubelab-bee |
| .4 | k3s-server |
| .5 | kubelab-rpi4 |
| .6 | kubelab-rpi3 |
| .7 | k3s-agent-1 |
| .8 | kubelab-jet1 |
| .9 | k3s-agent-2 |

#### DNS configuration (required for staging monitors)

The Uptime Kuma container uses Docker bridge networking. By default, Docker's internal DNS
forwards to the host's external resolvers (e.g., ISP DNS), which cannot resolve
`*.staging.kubelab.live` — those domains only resolve via Pi-hole/Tailscale MagicDNS.

**Fix**: The `compose.yml` on RPi3 must include explicit DNS pointing to Pi-hole:

```yaml
# ~/uptime-kuma/compose.yml on kubelab-rpi3
services:
  uptime-kuma:
    image: louislam/uptime-kuma:2
    container_name: uptime-kuma
    restart: unless-stopped
    ports:
      - "3001:3001"
    dns:
      - 100.64.0.10    # RPi4 Pi-hole (via Tailscale)
      - 1.1.1.1        # Fallback for public domains
    volumes:
      - uptime_kuma_data:/app/data

volumes:
  uptime_kuma_data:
```

After editing: `docker compose down && docker compose up -d`

#### Backup & restore (toolkit)

Uptime Kuma v2.x removed the UI backup/import feature. The SQLite database
(`kuma.db`) is the single source of truth for all monitors, status pages, and settings.

**Two-layer backup strategy**:

| Layer | Location | Purpose | Retention |
|-------|----------|---------|-----------|
| Repo | `infra/config/uptime-kuma/kuma.db` | Disaster recovery (RPi3 dies) | Git history (infinite) |
| Local RPi3 | `~/backups/kuma-YYYYMMDD.db` | Quick "oops" recovery | 7-day rolling |

**Layer 1 — Repo snapshot (from workstation, after significant changes)**:

```bash
toolkit monitoring backup     # pulls kuma.db from RPi3 → repo
toolkit monitoring status     # check Uptime Kuma health
toolkit monitoring restore    # push repo kuma.db → RPi3 (overwrites — use with caution)
```

The toolkit commands handle the full workflow: SSH to RPi3, `docker cp` from the
running container, `scp` to workstation, and cleanup.

**Layer 2 — Local rolling backup (cron on RPi3)**:

```bash
# Crontab entry on kubelab-rpi3 (crontab -e):
0 3 * * * docker cp uptime-kuma:/app/data/kuma.db /home/manu/backups/kuma-$(date +\%Y\%m\%d).db && find /home/manu/backups -name "kuma-*.db" -mtime +7 -delete
```

Creates `kuma-20260222.db` etc. The `find -mtime +7 -delete` auto-removes backups older than 7 days.
~3MB each, max ~21MB.

```bash
# Initial setup on RPi3:
mkdir -p ~/backups
```

To restore from a local backup (on RPi3 directly):

```bash
cd ~/uptime-kuma && docker compose down
docker run --rm \
  -v uptime-kuma_uptime_kuma_data:/data \
  -v /home/manu/backups:/backup \
  alpine cp /backup/kuma-20260222.db /data/kuma.db    # pick the date you want
docker compose up -d
```

#### Alert configuration (MON-006) ✓ Configured 2026-02-22

- **Notification method**: Slack Incoming Webhook → `#alerts` channel
- Alert on: any monitor down > 2 consecutive checks
- Uptime Kuma supports: Telegram, Discord, Slack, email, webhook, Gotify, Ntfy
- **Setup**: Uptime Kuma UI → Settings → Notifications → Slack Incoming Webhook
- **Webhook URL**: stored in Uptime Kuma settings (not in SOPS — Uptime Kuma manages its own config)

## Verification

Run the health endpoint check script and confirm all endpoints return `OK`.

```bash
curl -f https://mlorente.dev
curl -f https://blog.kubelab.live
curl -f https://api.kubelab.live/health
```

## Rollback

If monitoring reveals a failing service, restart it:

```bash
# Preferred: toolkit
toolkit services down <service_name>
toolkit services up <service_name>

# Fallback: raw Docker
docker restart $(docker ps -q -f name=<service_name>)
```

For a full recovery, see [deployment](../troubleshooting/deployment.md) rollback procedures.

## Last tested

2026-02-22
