---
id: rpi3-disaster-recovery
type: runbook
status: active
created: "2026-03-27"
owner: manu
---


# RPi3 Disaster Recovery

## Scenario
RPi3 SD card fails or RPi3 hardware needs replacement. Need to restore external monitoring (Uptime Kuma + Glances) from scratch.

## Prerequisites
- Fresh Raspberry Pi with Debian 13 (trixie) flashed on SD card
- RPi3 connected to network (temporary DHCP or static IP)
- SSH access configured (key or password)
- Tailscale installed and joined to Headscale (`vpn.kubelab.live`)

## Recovery Steps

### 1. Flash and prepare OS
```bash
# Flash Debian 13 arm64 to SD card
# Boot RPi3, connect via temporary IP
ssh manu@<temporary-ip>
# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --login-server=https://vpn.kubelab.live
```

### 2. Provision via Ansible
```bash
# From workstation (kubelab repo)
make provision NODE=rpi3 ENV=prod
```

This runs:
- **ssh_hardening** — hardened sshd_config
- **dns_resilience** — /etc/hosts entry for vpn.kubelab.live (public IP)
- **rpi3_services** — Docker Compose with Uptime Kuma + Glances
- **monitoring bootstrap** — creates admin user from SOPS + imports monitors from seed

### 3. Verify
```bash
make monitoring-status     # Check RPi3 + containers + HTTP
make monitoring-export     # Re-export to verify monitors match seed
```

### 4. Validate dashboard
- Access `https://status.kubelab.live` (VPS Traefik → RPi3)
- Login with SSOT credentials: `make secrets-show KEY=apps.services.observability.uptime_kuma.admin_password`
- Verify 25 monitors are active and collecting data

## Recovery Time Estimate
- OS flash + boot: 10 min
- Tailscale join: 2 min
- `make provision`: 3 min
- Total: ~15 min

## Key Files
- Ansible playbook: `infra/ansible/playbooks/provision-rpi3.yml`
- Ansible role: `infra/ansible/roles/rpi3_services/`
- Monitor seed: `infra/config/uptime-kuma/monitors.json`
- Notification seed: `infra/config/uptime-kuma/notifications.json`
- SOPS credentials: `apps.services.observability.uptime_kuma.*` in common.enc.yaml

## Notes
- RPi3 has NO LAN IP — Tailscale only (external to homelab for independent monitoring)
- Docker volume `uptime-kuma_uptime_kuma_data` preserves data across compose recreates
- Bootstrap is idempotent — safe to re-run on existing instance
- If upload_backup times out on import, monitors can be added manually or via `make monitoring-import` after provisioning
