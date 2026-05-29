---
id: "kubelab-runbook-proxmox-setup"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-10"
owner: manu
---

# Proxmox Setup

## Overview

Install and configure Proxmox VE 9.x on Acemagic miniPCs for K3s cluster hosting. Acemagic-1 (`kubelab-ace1`, 12GB) runs k3s-server + k3s-agent-1 VMs. Acemagic-2 (`kubelab-ace2`, 12GB) runs k3s-agent-2 VM for heavy workloads. A USB WiFi dongle provides backup management access if Ethernet networking fails.

## Prerequisites

- Acemagic miniPCs (12GB RAM each, SSD)
- USB drive with Proxmox VE 9.x ISO
- USB WiFi dongle (for backup management)
- Monitor + keyboard for initial setup
- Network cables connected to TP-Link switch

## Steps

### 1. Install Proxmox VE

1. Download Proxmox VE 9.x ISO from https://www.proxmox.com/en/downloads
2. Flash ISO to USB drive:

```bash
# On workstation (replace /dev/sdX with your USB device)
sudo dd if=proxmox-ve_9.x.iso of=/dev/sdX bs=4M status=progress
sync
```

3. Boot Acemagic from USB (press F7 or Del for boot menu)
4. Follow Proxmox installer:
   - Accept EULA
   - Target disk: select the SSD
   - Country/timezone: set appropriately
   - Password: set root password
   - Management interface: select **Ethernet** (NOT WiFi)
   - Hostname: `kubelab-ace1` (or `kubelab-ace2` for second node)
   - IP: use DHCP or set a static IP in your LAN range
5. Complete installation, remove USB, reboot

> **Note (PVE 9)**: Proxmox defaults management IP to `192.168.100.2`. You will likely need to reconfigure `/etc/network/interfaces` to match your actual LAN subnet after first boot.

### 2. Initial Configuration

Access Proxmox web UI at `https://<acemagic-ip>:8006` (login as `root`).

**Fix DNS resolution (PVE 9 defaults to localhost):**

```bash
ssh root@<acemagic-ip>

# PVE 9 sets /etc/resolv.conf to 127.0.0.1 by default — fix it
echo "nameserver 8.8.8.8" > /etc/resolv.conf
```

**Fix clock sync (fresh Proxmox installs may have wrong time):**

```bash
timedatectl set-ntp true
# If time is very far off, NTP sync may fail. Set manually first:
timedatectl set-time "2026-02-19 18:00:00"
timedatectl set-ntp true
```

**Remove subscription nag (optional for home use):**

```bash
# In PVE 9, enterprise repos use .sources format (not .list)
# Comment out the enterprise source
sed -i 's/^Types/#Types/' /etc/apt/sources.list.d/pve-enterprise.sources
sed -i 's/^URIs/#URIs/' /etc/apt/sources.list.d/pve-enterprise.sources
sed -i 's/^Suites/#Suites/' /etc/apt/sources.list.d/pve-enterprise.sources
sed -i 's/^Components/#Components/' /etc/apt/sources.list.d/pve-enterprise.sources

# Add no-subscription repository
echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" > /etc/apt/sources.list.d/pve-no-subscription.list

# Update
apt update && apt dist-upgrade -y
```

### 3. Bridge Networking for Ethernet

Proxmox creates a bridge (`vmbr0`) by default during installation. VMs connected to this bridge get IPs from RPi 4 dnsmasq DHCP (172.16.1.0/24 subnet).

Verify the bridge configuration:

```bash
cat /etc/network/interfaces
```

Expected (simplified):

```
auto lo
iface lo inet loopback

auto enp1s0
iface enp1s0 inet manual

auto vmbr0
iface vmbr0 inet dhcp
    bridge-ports enp1s0
    bridge-stp off
    bridge-fd 0
```

> **Key**: `vmbr0` bridges to the physical Ethernet (`enp1s0`). VMs use `vmbr0` and appear as regular devices on the LAN. RPi 4 dnsmasq handles DHCP — no NAT on Proxmox.

### 4. WiFi Dongle as Backup Management

The WiFi dongle provides an alternative management path if Ethernet networking fails (e.g., switch issues, bridge misconfiguration).

```bash
ssh root@<acemagic-ip>

# Identify the WiFi adapter
ip link show
# Look for a wlan device (e.g., wlp2s0 or wlan0)

# Install wireless tools
apt install -y wpasupplicant wireless-tools

# Create WPA supplicant config
cat > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf << 'EOF'
network={
    ssid="YOUR_WIFI_SSID"
    psk="YOUR_WIFI_PASSWORD"
}
EOF

# Configure the WiFi interface (backup only — NOT bridged)
cat >> /etc/network/interfaces << 'EOF'

# WiFi backup management interface (out-of-band)
auto wlan0
iface wlan0 inet dhcp
    wpa-conf /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
EOF

# Bring up WiFi
ifup wlan0
ip addr show wlan0
```

> **Important**: The WiFi interface is NOT bridged to `vmbr0`. It's a separate management path. VMs only use Ethernet via `vmbr0`. WiFi is for emergency SSH access to Proxmox if the Ethernet path breaks.

### 5. Resource Budget

With 12GB RAM per Acemagic, budget the Proxmox host:

| Component | RAM |
|-----------|-----|
| Proxmox VE OS | ~1.5-2 GB |
| Available for VMs | ~10 GB |

**Acemagic-1 VM allocations:**
- k3s-server: 5 GB
- k3s-agent-1: 5 GB

**Acemagic-2 VM allocations:**
- k3s-agent-2: ~10 GB (heavy workloads: observability, data)

### 6. Create K3s VMs

#### 6.1 Download Debian 13 ISO to Proxmox local storage

Download directly on each Proxmox host (faster than uploading via web UI):

```bash
# On ace1 (as root)
wget -P /var/lib/vz/template/iso/ https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.3.0-amd64-netinst.iso

# On ace2 (as root)
wget -P /var/lib/vz/template/iso/ https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.3.0-amd64-netinst.iso
```

> **Why netinst?** ~600MB vs ~4GB for full ISO. Packages install from internet during setup. RPi 4 gateway provides internet via NAT.
> **Why wget instead of web UI upload?** Reproducible, scriptable, faster over LAN.

#### 6.2 Create VMs via CLI (`qm create`)

Using CLI instead of web UI — reproducible, documentable, Ansible-ready.

**Design decisions:**
- **VM IDs**: 100/101 on ace1, 100 on ace2 (Proxmox default range, one cluster per host)
- **virtio-scsi-single**: Best disk performance for Linux guests
- **discard=on,ssd=1**: SSD optimization (both Acemagics have SSDs)
- **vmbr0 bridge**: VMs appear as regular LAN devices, get IPs from dnsmasq on RPi 4
- **Static IPs**: Configured inside the VM (not DHCP) — `172.16.1.10-12` range reserved for VMs
- **`--start 0`**: Don't auto-start — we boot manually after creation to install Debian via console

**On Acemagic-1** (`kubelab-ace1`, as root):

```bash
# VM 100: k3s-server (control plane)
qm create 100 \
  --name k3s-server \
  --memory 5120 \
  --cores 2 \
  --net0 virtio,bridge=vmbr0 \
  --scsihw virtio-scsi-single \
  --scsi0 local-lvm:40,discard=on,ssd=1 \
  --ide2 local:iso/debian-13.3.0-amd64-netinst.iso,media=cdrom \
  --boot order=ide2 \
  --ostype l26 \
  --start 0

# VM 101: k3s-agent-1 (worker)
qm create 101 \
  --name k3s-agent-1 \
  --memory 5120 \
  --cores 2 \
  --net0 virtio,bridge=vmbr0 \
  --scsihw virtio-scsi-single \
  --scsi0 local-lvm:40,discard=on,ssd=1 \
  --ide2 local:iso/debian-13.3.0-amd64-netinst.iso,media=cdrom \
  --boot order=ide2 \
  --ostype l26 \
  --start 0
```

> **Gotcha**: Double-check which SSH session you're in before running `qm create`. We accidentally created k3s-agent-1 on ace2 instead of ace1. Fix: `qm destroy 101 --purge` on ace2, then create on ace1. The `--purge` flag removes the LVM disk too.

**On Acemagic-2** (`kubelab-ace2`, as root):

```bash
# VM 100: k3s-agent-2 (heavy worker — observability, data)
qm create 100 \
  --name k3s-agent-2 \
  --memory 10240 \
  --cores 4 \
  --net0 virtio,bridge=vmbr0 \
  --scsihw virtio-scsi-single \
  --scsi0 local-lvm:50,discard=on,ssd=1 \
  --ide2 local:iso/debian-13.3.0-amd64-netinst.iso,media=cdrom \
  --boot order=ide2 \
  --ostype l26 \
  --start 0
```

#### 6.2.1 Enable auto-start on boot

By default, Proxmox VMs do NOT start automatically when the host reboots. Enable auto-start for all K3s VMs:

**On Acemagic-1** (as root):
```bash
qm set 100 --onboot 1
qm set 101 --onboot 1
```

**On Acemagic-2** (as root):
```bash
qm set 100 --onboot 1
```

> **Why this matters**: Without `--onboot 1`, every Proxmox reboot (power outage, maintenance, smart plug reset) leaves VMs stopped. The K3s cluster won't recover automatically.

#### 6.3 Install Debian 13 on each VM

Access Proxmox web UI console for each VM.

> **Gotcha**: The Proxmox web UI is on `172.16.1.x` (KubeLab LAN), not reachable directly from the workstation (`10.0.0.x`). Use SSH tunnels through RPi 4:
>
> ```bash
> # Terminal 1 — ace1 UI on localhost:8006
> ssh -L 8006:172.16.1.2:8006 rpi4 -N
>
> # Terminal 2 — ace2 UI on localhost:8007
> ssh -L 8007:172.16.1.5:8006 rpi4 -N
> ```
>
> Then open in browser (accept self-signed cert):
> - ace1: `https://localhost:8006` → VM 100, VM 101
> - ace2: `https://localhost:8007` → VM 100

Start VM (`qm start <vmid>` or via UI) → open Console → Debian installer:

1. **Language**: English
2. **Hostname**: `k3s-server` / `k3s-agent-1` / `k3s-agent-2`
3. **Domain**: (leave empty)
4. **Root password**: set a password
5. **User**: `manu` (consistent with all nodes)
6. **Partitioning**: Guided — use entire disk
7. **Software selection**: Only **SSH server** + **standard system utilities** (uncheck desktop, print server, etc.)
8. **GRUB**: Install to primary disk

> **Gotcha**: After Debian install, the VM reboots back into the installer because `--boot order=ide2` (CD-ROM) is still set. Fix: change boot order to disk and reboot:
> ```bash
> qm set <vmid> --boot order=scsi0
> qm reboot <vmid>
> ```
> This must be done for each VM after OS installation.
>
> **Gotcha**: `qm reboot` may fail with "VM quit/powerdown failed - got timeout" because the QEMU guest agent isn't installed yet on a fresh Debian. Use force stop + start instead:
> ```bash
> qm stop <vmid> && qm start <vmid>
> ```

#### 6.4 Configure static IPs inside each VM

After Debian install, login and configure networking:

```bash
# Edit /etc/network/interfaces
# Replace DHCP with static IP

auto ens18
iface ens18 inet static
    address 172.16.1.10/24    # .10 for server, .11 for agent-1, .12 for agent-2
    gateway 172.16.1.1        # RPi 4 gateway
    dns-nameservers 8.8.8.8 8.8.4.4
```

> **Why static instead of DHCP?** K3s nodes need stable IPs. DHCP reservations would work but static is simpler and doesn't depend on RPi 4 dnsmasq being up.

#### 6.5 Post-install on each VM

```bash
# Install sudo (not included in Debian minimal)
su -c 'apt install -y sudo && usermod -aG sudo manu'

# Copy SSH key from workstation
# (run from workstation, not the VM)
ssh-copy-id -o ProxyJump=rpi4 manu@172.16.1.10  # repeat for .11, .12
```

#### 6.6 Verify

```bash
# From workstation — all 3 VMs accessible
ssh -J rpi4 manu@172.16.1.10 'hostname && ip addr show ens18 | grep inet'
ssh -J rpi4 manu@172.16.1.11 'hostname && ip addr show ens18 | grep inet'
ssh -J rpi4 manu@172.16.1.12 'hostname && ip addr show ens18 | grep inet'

# From each VM — internet works via RPi 4 NAT
ping -c 3 8.8.8.8
ping -c 3 google.com
```

## Verification

```bash
# Proxmox web UI accessible
curl -k -s -o /dev/null -w "%{http_code}" https://<acemagic-ip>:8006
# Should return 200

# SSH via Ethernet
ssh root@<acemagic-ethernet-ip> 'hostname && free -h && pveversion'

# SSH via WiFi (backup path)
ssh root@<acemagic-wifi-ip> 'hostname && free -h'

# Bridge is working
brctl show vmbr0
# Should show enp1s0 (or similar) as the bridge member

# Proxmox version
pveversion
# Expected: pve-manager/9.x.x
```

## Maintenance

| Task | Schedule | Command |
|------|----------|---------|
| Update Proxmox | Monthly | `apt update && apt dist-upgrade -y` |
| Check storage usage | Monthly | `df -h` |
| Verify WiFi backup | Quarterly | SSH via WiFi IP |
| Backup VM configs | Before changes | Proxmox UI > Backup |

## Troubleshooting

**Can't access web UI after bridge change:**
- Connect via WiFi backup: `ssh root@<wifi-ip>`
- Check bridge config: `cat /etc/network/interfaces`
- Restart networking: `systemctl restart networking`

**Proxmox defaults to 192.168.100.2 (PVE 9):**
- The installer may assign `192.168.100.2` as the management IP regardless of DHCP
- Fix: edit `/etc/network/interfaces`, change `vmbr0` to your actual subnet (e.g., `172.16.1.2`)
- Restart networking or reboot

**DNS not working after install (PVE 9):**
- `/etc/resolv.conf` defaults to `nameserver 127.0.0.1`
- Fix: `echo "nameserver 8.8.8.8" > /etc/resolv.conf`
- Then `apt update` should work

**Clock is wrong / NTP fails:**
- Fresh installs may have very wrong system time, causing TLS and NTP issues
- Fix: `timedatectl set-time "YYYY-MM-DD HH:MM:SS"` then `timedatectl set-ntp true`

**`sudo` not installed / `usermod` not found (PVE 9 Debian minimal):**
- Proxmox ships without `sudo` and `usermod` is in `/usr/sbin/` (not in regular user's PATH)
- **Wrong**: running `su -` then pasting multi-line commands — `su -` opens a subshell, the next lines run as the original user after `exit`
- **Right**: single-line `su -c` to run everything as root in one shot:
  ```bash
  su -c 'apt install -y sudo && /usr/sbin/usermod -aG sudo manu'
  ```
- After installing, log out and back in for the `sudo` group to take effect

**VMs disappear after hostname rename (`qm list` empty):**
- Proxmox ties VM configs to the node name under `/etc/pve/nodes/{hostname}/qemu-server/`
- If you rename the hostname (e.g., `cubelab-ace1` → `kubelab-ace1`), Proxmox creates a new node directory but VM configs stay under the old one
- Diagnosis: `ls /etc/pve/nodes/` — you'll see both old and new directories
- The `.conf` files exist under the old dir: `ls /etc/pve/nodes/{old-hostname}/qemu-server/`
- Fix: move configs to the new node directory:
  ```bash
  mv /etc/pve/nodes/{old-hostname}/qemu-server/*.conf /etc/pve/nodes/{new-hostname}/qemu-server/
  qm list          # VMs should now appear
  qm start <vmid>  # Start them
  ```
- After confirming VMs work, clean up the old empty directory
- **Rule**: Never rename a Proxmox host with just `hostnamectl`. Always check `/etc/pve/nodes/` and move VM configs.

**WiFi dongle not detected:**
- Check: `lsusb` — dongle should appear
- Check: `dmesg | grep -i wifi` for driver messages
- Some dongles need firmware: `apt install firmware-realtek` (or similar)

**VMs not getting DHCP:**
- Verify bridge: `brctl show vmbr0`
- Verify VM network is set to `vmbr0`
- Check home router DHCP pool has room

## Related

- [hardware-setup](hardware-setup.md) — Acemagic provisioning and full hardware checklist
- [tailscale-setup](tailscale-setup.md) — Install Tailscale on Proxmox host

## Last tested

- 2026-02-19: Proxmox VE 9.1.5 installed on Acemagic-1 (kubelab-ace1) and Acemagic-2 (kubelab-ace2). Both accessible via web UI and SSH. Enterprise repos are `.sources` format in PVE 9 (not `.list`). Default IP was 192.168.100.2 — required manual reconfiguration. DNS fix needed (`/etc/resolv.conf` → `8.8.8.8`). Clock sync required on fresh install (`timedatectl`). dnsmasq on RPi 4 needed `bind-dynamic` to handle timing issues with devices connecting before DHCP was ready.
