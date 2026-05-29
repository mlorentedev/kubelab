---
id: "kubelab-runbook-hardware-setup"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-09"
owner: manu
---

# Hardware Setup — B0 Checklist

Provision KubeLab homelab hardware with the correct OS, SSH access, and networking. This runbook covers the manual steps performed before Ansible takes over automated provisioning.

**Devices to provision:**
1. Acemagic-1 (12GB) → Proxmox VE 9.x (K3s server + agent-1 VMs) ✓ Done 2026-02-19
2. Acemagic-2 (12GB) → Proxmox VE 9.x (K3s agent-2 VM) ✓ Done 2026-02-19
3. Beelink (8GB) → Ubuntu Server 24.04 LTS + Ollama (OS installed ✓ 2026-02-19, Ollama pending)
4. Raspberry Pi 4B (8GB) → Ubuntu Server 24.04 LTS (gateway + agents) ✓ Done
5. Raspberry Pi 3B+ (1GB) → Raspberry Pi OS Lite (external monitor) ✓ Done
6. Jetson Nano (4GB) → JetPack (Ubuntu) + CUDA ✓ Done (hostname renamed 2026-02-19)

**User convention**: `manu` on all homelab nodes. Avoids `kubelab@kubelab-*` prompt redundancy.

## Prerequisites

**Gather before starting:**

- [x] USB drive with Proxmox VE 9.x installer (×2, for both Acemagics) ✓
- [x] USB drive with Ubuntu Server 24.04 LTS installer (for Beelink) ✓
- [ ] SD card 128GB flashed with Ubuntu Server 24.04 LTS arm64 (for RPi 4) ✓
- [ ] SD card 64GB flashed with Raspberry Pi OS Lite (for RPi 3) ✓
- [ ] SD card 256GB with JetPack image (for Jetson Nano) ✓
- [ ] USB 3.0 Ethernet adapter for RPi 4 (uplink, confirmed 1Gbps) ✓
- [ ] Ethernet cables: router→RPi4-USB, RPi4→switch, switch→Acemagic-1, switch→Acemagic-2, switch→Beelink, switch→Jetson, router→RPi3 (WiFi dongle)
- [ ] TP-Link TL-SG switch powered and ready ✓
- [ ] Monitor + keyboard for initial setup
- [ ] SSH public key from workstation (`~/.ssh/id_ed25519.pub`)

---

## Phase 1: OS Installation

### 1.1 Acemagic-1 — Proxmox K3s Node 1 (`kubelab-ace1`) ✓ Done 2026-02-19

```
Hostname: kubelab-ace1
OS: Proxmox VE 9.1.5 (Debian-based)
RAM: 12GB | Storage: SSD
```

- [x] Download Proxmox VE 9.x ISO from https://www.proxmox.com/en/downloads
- [x] Flash ISO to USB drive (Balena Etcher or `dd`)
- [x] Boot Acemagic-1 from USB installer
- [x] During installation:
  - Management interface: Ethernet
  - Hostname: `kubelab-ace1`
  - Set root password
  - Management IP: DHCP initially (will get `172.16.1.2` via dnsmasq reservation)
- [x] After install, access Proxmox web UI at `https://172.16.1.2:8006`
- [x] Add SSH key for `manu` user:
  ```bash
  # In Proxmox shell or via root SSH
  useradd -m -s /bin/bash manu
  usermod -aG sudo manu
  mkdir -p /home/manu/.ssh
  echo "<your-pubkey>" >> /home/manu/.ssh/authorized_keys
  chmod 700 /home/manu/.ssh && chmod 600 /home/manu/.ssh/authorized_keys
  chown -R manu:manu /home/manu/.ssh
  ```

See [proxmox-setup](proxmox-setup.md) for VM creation and configuration details.

**Create VMs on Acemagic-1:**

- [x] Create VM `k3s-server`: 5GB RAM, 2 vCPU, 40GB disk, Debian 13, IP `172.16.1.10` ✓ 2026-02-19
- [x] Create VM `k3s-agent-1`: 5GB RAM, 2 vCPU, 40GB disk, Debian 13, IP `172.16.1.11` ✓ 2026-02-19
- [x] Install Debian 13 in each VM (minimal, SSH server enabled) ✓ 2026-02-19
- [ ] Add `manu` user + SSH key in each VM

### 1.2 Acemagic-2 — Proxmox K3s Node 2 (`kubelab-ace2`) ✓ Done 2026-02-19

```
Hostname: kubelab-ace2
OS: Proxmox VE 9.1.5 (Debian-based)
RAM: 12GB | Storage: SSD
```

- [x] Boot Acemagic-2 from Proxmox USB installer
- [x] During installation:
  - Hostname: `kubelab-ace2`
  - Management IP: DHCP (will get `172.16.1.5` via dnsmasq reservation)
- [x] Add SSH key for `manu` user (same as Acemagic-1)

**Create VM on Acemagic-2:**

- [x] Create VM `k3s-agent-2`: 10GB RAM, 4 vCPU, 50GB disk, Debian 13, IP `172.16.1.12` ✓ 2026-02-19
- [x] Install Debian 13 (minimal, SSH server enabled) ✓ 2026-02-19
- [ ] Add `manu` user + SSH key

### 1.3 Beelink — Ollama LLM API (`kubelab-bee`) — OS installed ✓ 2026-02-19, Ollama pending

```
Hostname: kubelab-bee
Username: manu
OS: Ubuntu Server 24.04 LTS (bare metal — no Proxmox)
RAM: 8GB | Storage: SSD
```

- [x] Flash Ubuntu Server 24.04 LTS ISO to USB (or use the same one from RPi 4 if amd64)
- [x] Boot from USB installer
- [x] In the installer:
  - Hostname: `kubelab-bee`
  - User: `manu`
  - Enable OpenSSH Server
  - Minimal install (no snaps, no extras)
- [x] After install, add SSH key and update:

```bash
sudo apt update && sudo apt upgrade -y
# Optionally disable snap if you want minimal overhead:
sudo systemctl disable snapd && sudo systemctl stop snapd
```

- [x] Install Ollama ✓ 2026-02-19:

```bash
curl -fsSL https://ollama.com/install.sh | sh
# Installs to /usr/local, creates ollama user + systemd service
# CPU-only mode (Intel N95 has no dedicated GPU)
```

- [x] Configure Ollama to listen on LAN (default: localhost only) ✓ 2026-02-19:

```bash
sudo systemctl edit ollama
# Add:
# [Service]
# Environment="OLLAMA_HOST=0.0.0.0"
sudo systemctl restart ollama
```

- [x] Pull initial model ✓ 2026-02-19:

```bash
ollama pull qwen2.5:7b  # ~4.7GB, best quality that fits in 8GB RAM
# Decision: 7B is the ceiling for 8GB RAM — 14B would swap-thrash
# Alternatives considered: vLLM (overkill, needs GPU), LocalAI (more complex), llama.cpp (already on Jetson)
```

- [x] Verify (local + LAN) ✓ 2026-02-19:

```bash
# Local
curl http://localhost:11434/api/tags
# LAN (from RPi 4 — confirms agent→Ollama path works)
curl http://172.16.1.3:11434/api/tags
# Smoke test
ollama run qwen2.5:7b "Say hello in 3 words"
```

### 1.4 RPi 4 — Gateway + Agent Node (`kubelab-rpi4`) ✓ Already provisioned

```
Hostname: kubelab-rpi4
Username: manu (or ubuntu — rename if needed)
OS: Ubuntu Server 24.04 LTS (arm64)
RAM: 8GB | Storage: SD 128GB
Status: ONLINE — NAT gateway + dnsmasq DHCP operational
```

- [x] Ubuntu Server installed
- [x] USB 3.0 Ethernet adapter as WAN uplink (`enx00249b1b0d6b`, ASIX AX88179 Gigabit)
  - **Previous adapter** (`enx00e04c690e15`) replaced. Netplan interface name updated 2026-02-21.
- [x] Built-in Ethernet as LAN downlink (`eth0`, `172.16.1.1`)
- [x] IP forwarding enabled (`/etc/sysctl.d/99-gateway.conf`)
- [x] nftables NAT masquerade configured
- [x] dnsmasq DHCP running (`/etc/dnsmasq.d/kubelab-dhcp.conf`)
- [x] **Rename hostname** from `kubelab-rpi4-edge` → `kubelab-rpi4` ✓ 2026-02-19
  - Applied `hostnamectl set-hostname` + `preserve_hostname: true` in `/etc/cloud/cloud.cfg` (cloud-init was resetting it on boot)
- [ ] **Add dnsmasq reservations** for VMs (k3s-server, k3s-agent-1, k3s-agent-2)

### 1.5 RPi 3 — External Monitor (`kubelab-rpi3`) ✓ Provisioned 2026-02-18

```
Hostname: kubelab-rpi3
Username: manu
OS: Raspberry Pi OS Lite (64-bit, Bookworm)
RAM: 1GB | Storage: SD 64GB
IP: 10.0.0.157 (router DHCP, built-in WiFi)
Status: ONLINE — WiFi configured, SSH accessible
```

- [x] Raspberry Pi OS Lite installed (64-bit Bookworm)
- [x] WiFi connected to home router via built-in `wlan0` (NOT dongle — simpler setup)
- [x] Hostname set to `kubelab-rpi3`
- [x] User `manu` created
- [x] SSH enabled and accessible at `10.0.0.157`
- [x] `/etc/hosts` entry added: `127.0.1.1 kubelab-rpi3`

**WiFi setup that worked** (see troubleshooting below if issues):

```bash
# 1. Set WiFi country (REQUIRED on RPi OS Lite — without this the radio is disabled)
sudo raspi-config nonint do_wifi_country ES
sudo reboot

# 2. After reboot, rescan and connect
sudo nmcli dev wifi rescan
sleep 3
sudo nmcli dev wifi connect "SSID" password "PASSWORD"

# 3. Make autoconnect explicit
sudo nmcli connection modify "SSID" connection.autoconnect yes

# 4. Fix hostname resolution warning
echo "127.0.1.1 kubelab-rpi3" | sudo tee -a /etc/hosts
```

> **Troubleshooting WiFi on RPi OS Lite**: see [networking-dns](../troubleshooting/networking-dns.md#rpi-os-lite-wifi)

### 1.6 Jetson Nano #1 — AI Node (`kubelab-jet1`)

```
Hostname: kubelab-jet1
OS: JetPack (Ubuntu-based) + CUDA
RAM: 4GB | Storage: SD 256GB
Status: ONLINE — hostname renamed ✓ 2026-02-19
```

- [x] JetPack installed, internet access verified
- [x] **Rename hostname** ✓ 2026-02-19:
  ```bash
  sudo hostnamectl set-hostname kubelab-jet1
  ```
- [ ] Verify CUDA:
  ```bash
  nvcc --version
  ```
- [ ] Install Docker if not pre-installed:
  ```bash
  sudo apt update && sudo apt install -y docker.io docker-compose-plugin
  sudo usermod -aG docker manu
  ```

---

## Phase 2: Network Cabling

**Target topology:**

```
[Home Router]
  ├── WiFi ──→ [RPi 3] (kubelab-rpi3) ← WiFi dongle, independent path, diff location
  │
  └── ETH ──→ [RPi 4 USB ETH adapter] (kubelab-rpi4) ← uplink
                │
                └── [RPi 4 built-in ETH] ← downlink
                       │
                       └──→ [TP-Link Switch]
                              ├── [Acemagic-1] (kubelab-ace1) → Proxmox
                              ├── [Acemagic-2] (kubelab-ace2) → Proxmox
                              ├── [Beelink]    (kubelab-bee)  → Ubuntu 24.04 + Ollama
                              └── [Jetson]     (kubelab-jet1) → JetPack
```

- [x] USB 3.0 Ethernet adapter on RPi 4 → home router (uplink)
- [x] RPi 4 built-in Ethernet → TP-Link switch (downlink)
- [x] RPi 3 → home router via WiFi (independent, separate location)
- [x] Jetson → TP-Link switch ✓
- [x] Beelink → TP-Link switch ✓ (Ubuntu Server 24.04 installed)
- [x] Acemagic-1 → TP-Link switch ✓
- [x] Acemagic-2 → TP-Link switch ✓

---

## Phase 3: DHCP Reservations on RPi 4

Update `/etc/dnsmasq.d/kubelab-dhcp.conf` with new devices:

```ini
# KubeLab DHCP server — RPi 4 gateway
port=0
interface=eth0
bind-interfaces

dhcp-range=172.16.1.50,172.16.1.150,255.255.255.0,12h

# Gateway and DNS for clients
dhcp-option=option:router,172.16.1.1
dhcp-option=option:dns-server,8.8.8.8,1.1.1.1

# Static reservations
dhcp-host=68:1D:EF:38:C5:6F,kubelab-ace1,172.16.1.2
dhcp-host=68:1D:EF:38:C5:8B,kubelab-ace2,172.16.1.5
dhcp-host=78:55:36:06:18:14,kubelab-bee,172.16.1.3
dhcp-host=00:04:4b:e5:5f:28,kubelab-jet1,172.16.1.4
# K3s VMs get IPs assigned in Proxmox netplan (static)
```

> Note: Proxmox VMs get static IPs via their own netplan config (not DHCP reservation) because
> Proxmox bridges to the LAN and VMs are seen as distinct MAC addresses. Assign 172.16.1.10-12 statically inside each VM.

Reload dnsmasq:
```bash
sudo systemctl restart dnsmasq
```

**IP reference table:**

| Device | Hostname | IP | MAC |
|--------|----------|----|-----|
| RPi 4 (LAN) | kubelab-rpi4 | `172.16.1.1` | `e4:5f:01:fd:b0:81` |
| RPi 4 (WAN USB) | — | `10.0.0.88` (DHCP not working as of 2026-03-14, Xfinity router issue) | `00:24:9b:1b:0d:6b` |
| RPi 4 (WiFi) | — | `10.0.0.131` | `e4:5f:01:fd:b0:82` |
| RPi 4 (Tailscale) | — | `100.64.0.10` (was .5, changed 2026-03-14 after SD reflash) | — |
| RPi 3 | kubelab-rpi3 | `10.0.0.157` (WiFi, router DHCP) | `b8:27:eb:xx:xx:xx` |
| Acemagic-1 | kubelab-ace1 | `172.16.1.2` | `68:1D:EF:38:C5:6F` |
| k3s-server VM | k3s-server | `172.16.1.10` | static in VM |
| k3s-agent-1 VM | k3s-agent-1 | `172.16.1.11` | static in VM |
| Acemagic-2 | kubelab-ace2 | `172.16.1.5` | `68:1D:EF:38:C5:8B` |
| k3s-agent-2 VM | k3s-agent-2 | `172.16.1.12` | static in VM |
| Beelink | kubelab-bee | `172.16.1.3` | `78:55:36:06:18:14` |
| Jetson #1 | kubelab-jet1 | `172.16.1.4` | `00:04:4b:e5:5f:28` |

---

## Phase 4: RPi 4 Bridge/NAT (Already Configured ✓)

The RPi 4 NAT gateway was configured on 2026-02-17. Verified operational.

Reference (already applied):

| Interface | Name | Role | Metric |
|-----------|------|------|--------|
| USB 3.0 Ethernet | `enx00249b1b0d6b` | WAN uplink (router) | 100 (primary) |
| Built-in Ethernet | `eth0` | LAN downlink (switch) | — |
| WiFi | `wlan0` | WAN backup (router) | 600 (failover) |

**Failover**: automatic via route metrics. If USB Ethernet cable disconnects, Linux routes
traffic through WiFi (metric 600). No manual intervention needed.

**Netplan gotcha**: interface names use MAC-based naming (`enx<MAC>`). If you swap the USB
adapter, update `/etc/netplan/50-cloud-init.yaml` with the new interface name (`ip link show`
to find it), then `sudo netplan apply`.

**Cloud-init protection**: disable cloud-init network config to prevent it from overwriting
netplan on boot:
```bash
echo "network: {config: disabled}" | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
```
Applied ✓ (2026-02-21).

---

## Phase 5: SSH Keys & Verification

- [x] Copy SSH key to Proxmox hosts and Beelink and Jetson ✓ 2026-02-19:

```bash
ssh-copy-id manu@172.16.1.2    # Acemagic-1 (Proxmox host) ✓
ssh-copy-id manu@172.16.1.5    # Acemagic-2 (Proxmox host) ✓
ssh-copy-id manu@172.16.1.3    # Beelink ✓
ssh-copy-id manu@172.16.1.4    # Jetson ✓
```

- [ ] Copy SSH key to VMs (pending VM creation):

```bash
ssh-copy-id manu@172.16.1.10   # k3s-server VM
ssh-copy-id manu@172.16.1.11   # k3s-agent-1 VM
ssh-copy-id manu@172.16.1.12   # k3s-agent-2 VM
```

- [x] Verify SSH access to Proxmox hosts + Beelink + Jetson ✓ 2026-02-19:

```bash
ssh manu@172.16.1.2 'hostname && free -h'   # kubelab-ace1 Proxmox ✓
ssh manu@172.16.1.5 'hostname && free -h'   # kubelab-ace2 Proxmox ✓
ssh manu@172.16.1.3 'hostname && free -h'   # kubelab-bee ✓
ssh manu@172.16.1.4 'hostname && nvcc --version'  # kubelab-jet1 ✓
```

- [ ] Verify SSH access to VMs (pending VM creation):

```bash
ssh manu@172.16.1.10 'hostname && free -h'  # k3s-server
ssh manu@172.16.1.11 'hostname && free -h'  # k3s-agent-1
ssh manu@172.16.1.12 'hostname && free -h'  # k3s-agent-2
```

- [ ] Verify internet through RPi 4 bridge from all new devices:

```bash
ssh manu@172.16.1.2 'ping -c 3 8.8.8.8'   # Acemagic-1
ssh manu@172.16.1.3 'ping -c 3 8.8.8.8'   # Beelink
```

---

## Quick Reference Card

| Device | Hostname | IP | Subnet | User | SSH |
|--------|----------|----|--------|------|-----|
| RPi 4 (WAN) | kubelab-rpi4 | `10.0.0.131` | Router DHCP | manu | ✓ |
| RPi 4 (LAN) | kubelab-rpi4 | `172.16.1.1` | Static | — | — |
| RPi 3 | kubelab-rpi3 | `10.0.0.157` | Router DHCP (WiFi) | manu | ✓ |
| Acemagic-1 | kubelab-ace1 | `172.16.1.2` | dnsmasq | manu | ✓ |
| k3s-server VM | k3s-server | `172.16.1.10` | static in VM | manu | ✓ Debian 13, SSH key |
| k3s-agent-1 VM | k3s-agent-1 | `172.16.1.11` | static in VM | manu | ✓ Debian 13, SSH key |
| Acemagic-2 | kubelab-ace2 | `172.16.1.5` | dnsmasq | manu | ✓ |
| k3s-agent-2 VM | k3s-agent-2 | `172.16.1.12` | static in VM | manu | ✓ Debian 13, SSH key |
| Beelink | kubelab-bee | `172.16.1.3` | dnsmasq | manu | ✓ |
| Jetson #1 | kubelab-jet1 | `172.16.1.4` | dnsmasq | manu | ✓ |

### SSH Aliases (`~/.ssh/config`)

All devices accessible from workstation via short aliases. **Primary path: Tailscale VPN** (works from anywhere). **Fallback: `-lan`** (LAN only, when VPN is down). **VPS: `-pub`** (public IP, no LAN).

```
# Primary (Tailscale VPN)          # Fallback (LAN / public)
rpi4        → 100.64.0.10          rpi4-lan        → 10.0.0.131
rpi3        → 100.64.0.6           rpi3-lan        → 10.0.0.157
bee         → 100.64.0.3           bee-lan         → 172.16.1.3  (ProxyJump rpi4-lan)
jet1        → 100.64.0.8           jet1-lan        → 172.16.1.4  (ProxyJump rpi4-lan)
k3s-server  → 100.64.0.4           k3s-server-lan  → 172.16.1.10 (ProxyJump rpi4-lan)
k3s-agent-1 → 100.64.0.7           k3s-agent-1-lan → 172.16.1.11 (ProxyJump rpi4-lan)
k3s-agent-2 → 100.64.0.9           k3s-agent-2-lan → 172.16.1.12 (ProxyJump rpi4-lan)
vps         → 100.64.0.2           vps-pub         → 162.55.57.175
ace1        → 172.16.1.2  (ProxyJump rpi4, no Tailscale on Proxmox hosts)
ace2        → 172.16.1.5  (ProxyJump rpi4, no Tailscale on Proxmox hosts)
```

> SSH config lives on the workstation (`~/.ssh/config`), not in the vault. This table is the reference to recreate it. See [headscale-setup](headscale-setup.md#Phase 5 SSH Config Update) for the full config block.

---

## Adding a New Node — Checklist

When adding a new physical device or VM to the homelab:

### 1. Hardware + OS
- [ ] Install OS (Ubuntu Server 24.04 LTS preferred, or device-specific like JetPack)
- [ ] Set hostname: `kubelab-<name>` (e.g., `kubelab-newnode`)
- [ ] Create user `manu` + copy SSH key (`ssh-copy-id`)
- [ ] Connect to switch (LAN) or WiFi (gateway nodes)
- [ ] If LAN: add DHCP reservation in `/etc/dnsmasq.d/kubelab-dhcp.conf` on RPi4 → restart dnsmasq
- [ ] Verify SSH: `ssh manu@<LAN-IP> 'hostname && free -h'`

### 2. Tailscale VPN → [headscale-setup](headscale-setup.md#Phase 2 Connect All Nodes)
- [ ] Install Tailscale: `curl -fsSL https://tailscale.com/install.sh | sh`
- [ ] Register: `sudo tailscale up --login-server=https://vpn.kubelab.live --authkey=<KEY>`
- [ ] Verify: `tailscale status` shows the new node with a `100.64.0.x` IP
- [ ] If `systemd-resolved` active: add FallbackDNS → [headscale-setup](headscale-setup.md#incident-jet1-dns-boot)
- [ ] If node runs Pi-hole (RPi4 only): use `--accept-dns=false` → [headscale-setup](headscale-setup.md#Phase 3)

### 3. DNS Resilience → [dns-homelab](dns-homelab.md#DNS Resilience — /etc/hosts Fallback via Ansible)
- [ ] Add node to `infra/ansible/inventories/homelab.yml` (hostname + Tailscale IP)
- [ ] If Python < 3.7 (e.g. JetPack/Ubuntu 18.04): add `legacy_python: true`
- [ ] Run: `ansible-playbook -i inventories/homelab.yml playbooks/homelab-dns.yml -K`
- [ ] Verify: `ssh <host> "grep vpn.kubelab.live /etc/hosts"` → `162.55.57.175 vpn.kubelab.live`

### 4. SSH Config (workstation)
- [ ] Add VPN alias in `~/.ssh/config`: `Host <name>` → `Hostname <tailscale-ip>`
- [ ] Add LAN fallback alias: `Host <name>-lan` → `Hostname <lan-ip>` (+ `ProxyJump rpi4-lan` if behind switch)
- [ ] Verify: `ssh <name> 'hostname'`

### 5. Documentation
- [ ] Update IP tables in this runbook (Quick Reference Card)
- [ ] Update  (Hardware Inventory + Topology + Headscale Mesh VPN)
- [ ] If node has a specific role: add a section in Phase 1

---

## Next Steps

After hardware is provisioned:
1. Deploy Pi-hole + CoreDNS on RPi 4 → see [pihole-setup](pihole-setup.md)
2. Set up Headscale on VPS + Tailscale clients on all nodes → see [headscale-setup](headscale-setup.md)
3. Configure CoreDNS for staging domain → see [dns-homelab](dns-homelab.md)
4. Apply DNS resilience to all nodes → see [dns-homelab](dns-homelab.md#DNS Resilience — /etc/hosts Fallback via Ansible)
5. Set up K3s cluster (B3) → tasks/todo.md
6. Deploy Uptime Kuma on RPi 3 (B7)

## Last tested

- 2026-02-17: RPi 4 gateway configured (IP forwarding + nftables NAT + dnsmasq DHCP). Jetson verified online (DHCP lease, internet via NAT). Beelink online (Windows, Debian pending). RPi 3 online (independent WiFi).
- 2026-02-18: Architecture updated — 2x Acemagic Proxmox, Beelink Ollama, Headscale VPN. RPi 3 fully provisioned: WiFi (built-in wlan0), hostname kubelab-rpi3, Docker installed, Uptime Kuma v2 deployed and monitoring VPS + RPi 4 + router.
- 2026-02-19: Proxmox VE 9.1.5 installed on Acemagic-1 (kubelab-ace1) and Acemagic-2 (kubelab-ace2). Ubuntu Server 24.04 LTS installed on Beelink (kubelab-bee). Jetson hostname renamed to kubelab-jet1. SSH keys copied to ace1, ace2, bee, jet1. All four devices on switch and accessible via SSH. Issues discovered: Proxmox default IP 192.168.100.2 (needs reconfiguration to LAN range), dnsmasq timing fix needed (bind-dynamic), clock sync needed on fresh Proxmox installs. Ollama on Beelink and VMs on Acemagics still pending.
