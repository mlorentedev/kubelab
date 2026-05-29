---
id: "kubelab-runbook-tailscale-setup"
type: runbook
status: superseded
tags: [runbook, kubelab]
created: "2026-02-09"
owner: manu
---

# Tailscale Setup

> **SUPERSEDED (2026-02-18)**: KubeLab now uses **Headscale** (self-hosted Tailscale control plane) instead of Tailscale cloud.
> Tailscale clients are still used on all nodes, but authentication points to the self-hosted Headscale server on the VPS.
>
> **→ See [headscale-setup](headscale-setup.md) for the current procedure.**
>
> This file is kept as historical reference. The client-side commands (install, `tailscale up`, `tailscale status`) are identical — only the `--login-server` flag differs.

---

## Overview (Historical)

Set up a Tailscale mesh VPN connecting the KubeLab homelab (Acemagic, RPi 4, RPi 3), workstation, and optionally mobile devices. Tailscale provides NAT traversal without requiring port forwarding on the router.

See [adr-006-tailscale-over-wireguard](../adr/adr-006-tailscale-over-wireguard.md) and [adr-010-headscale-over-tailscale-cloud](../adr/adr-010-headscale-over-tailscale-cloud.md) for the decision rationale.

## Prerequisites (Historical)

- Tailscale account (https://login.tailscale.com) — **no longer used, replaced by Headscale**
- SSH access to `kubelab-ace-staging` and `kubelab-rpi4`
- Hardware provisioned per [hardware-setup](hardware-setup.md)

## Steps

### 1. Install Tailscale on all devices

**On Acemagic and RPi 4** (Ubuntu Server 24.04):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

**On RPi 3** (Raspberry Pi OS Lite):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

**On workstation** (Linux):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

### 2. Authenticate each device

On each machine:

```bash
sudo tailscale up
# Follow the URL to authenticate in browser
```

### 3. Configure RPi 4 as subnet router

RPi 4 (`kubelab-rpi4`) advertises the KubeLab LAN subnet so Tailscale peers can reach devices behind the switch:

```bash
# On RPi 4 (IP forwarding already enabled for NAT gateway)
# Verify:
sysctl net.ipv4.ip_forward  # Should be 1

# Advertise the KubeLab LAN subnet
sudo tailscale up --advertise-routes=172.16.1.0/24
```

> **Note**: IPv6 forwarding is optional. Add if needed:
> `echo 'net.ipv6.conf.all.forwarding = 1' | sudo tee -a /etc/sysctl.d/99-tailscale.conf`

### 4. Approve subnet route

In the Tailscale admin console (https://login.tailscale.com/admin/machines):

1. Find `kubelab-rpi4`
2. Click "..." → "Edit route settings"
3. Approve the advertised subnet route (`172.16.1.0/24`)

### 5. Record Tailscale IPs

```bash
# On each machine
tailscale ip -4
```

Update the table:

| Device | Hostname | Tailscale IP | Role |
|--------|----------|-------------|------|
| Acemagic | kubelab-ace-staging | 100.x.x.x | Staging stack |
| RPi 4 | kubelab-rpi4 | 100.x.x.x | Gateway + DNS + agents |
| RPi 3 | kubelab-rpi3-monitor | 100.x.x.x | External monitoring |
| Beelink | kubelab-bee-pve | 100.x.x.x | Proxmox lab |
| workstation | — | 100.x.x.x | Development |

### 6. Configure Tailscale split DNS (for staging domains)

In Tailscale admin → DNS → Custom nameservers:

- Add RPi 4 Tailscale IP as nameserver
- Restrict to domain: `staging.kubelab.live`

This routes `*.staging.kubelab.live` queries to CoreDNS on RPi 4.

### 7. Update Ansible inventory

Edit `infra/ansible/generated/staging/hosts.yml`:

```yaml
ansible_host: 100.x.x.x  # Acemagic Tailscale IP
```

## Verification

```bash
# Ping between devices
tailscale ping kubelab-ace-staging
tailscale ping kubelab-rpi4

# SSH via Tailscale IP
ssh kubelab@<acemagic-tailscale-ip> 'hostname'
ssh kubelab@<rpi4-tailscale-ip> 'hostname'

# Check Tailscale status
tailscale status

# Verify subnet routing (from workstation, reach a device behind the switch):
ping 172.16.1.4  # Should reach Jetson via RPi 4 subnet route
```

## Troubleshooting

### Device not connecting
```bash
sudo tailscale status
sudo journalctl -u tailscaled -f
```

### Subnet route not working
```bash
# Verify IP forwarding
sysctl net.ipv4.ip_forward  # Should be 1

# Verify route is advertised
tailscale status --json | jq '.Self.AllowedIPs'

# Verify route is approved in admin console
```

### Tailscale IP changed
Tailscale IPs are stable by default. If they change:
1. Update Ansible inventory
2. Update CoreDNS Corefile
3. Consider using MagicDNS hostnames instead of IPs

## Next Steps

After Tailscale is set up:
1. Deploy CoreDNS on RPi 4 → see [dns-homelab](dns-homelab.md)
2. Run Ansible provisioning on Acemagic → see [deployment](../troubleshooting/deployment.md)

## Last tested

Not yet — pending hardware provisioning.
