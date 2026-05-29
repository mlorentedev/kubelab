---
id: rpi4-sd-card-provisioning
type: runbook
status: active
created: "2026-03-15"
owner: manu
---

# RPi4 SD Card Provisioning

## Purpose

Pre-configure an Ubuntu Server SD card for the RPi4 network gateway before first boot. The script (`infra/provisioning/rpi4/configure-sd.sh`) writes all network, DNS, NAT, and DHCP configs directly to the mounted filesystem so the RPi4 boots ready to serve as the KubeLab LAN gateway.

## When to Use

- Fresh RPi4 setup from scratch
- SD card replacement (corruption, upgrade)
- Disaster recovery of the RPi4 gateway node

## Prerequisites

1. **SD card flashed** with Ubuntu Server (ARM64) using Raspberry Pi Imager
   - Configure WiFi credentials, SSH, and user `manu` in the Imager before flashing
   - **Note (SSOT-014, 2026-05-25):** `manu` here is the **OS-level** Linux user that SSHes into the node — declared via SSOT at `networking.ssh_users.homelab` in `common.yaml`. It is **NOT** the same as the App-level Authelia admin (`apps.auth.admin_username`, e.g. `operator` post-Phase-B). They coincided by historical accident. Renaming the OS user requires `useradd` + key migration per node (tracked as `SSH-RENAME-001`); do not rename here without that plan.
2. **SD card mounted** on workstation at `/media/$USER/writable` and `/media/$USER/system-boot`
3. **Run from workstation**, not from the RPi4

## What the Script Configures (8 steps)

| Step | What | Detail |
|------|------|--------|
| 1 | Netplan | 3 interfaces: `eth0` static 172.16.1.1/24 (LAN), `enx*` USB Ethernet DHCP (uplink), `wlan0` WiFi DHCP (fallback). Extracts WiFi creds from Imager config. |
| 2 | Cloud-init | Disables cloud-init network management, preserves hostname |
| 3 | IP forwarding | Enables `net.ipv4.ip_forward=1` via sysctl |
| 4 | nftables NAT | Masquerade outbound traffic from LAN through USB Ethernet uplink |
| 5 | dnsmasq DHCP | Static leases for lab nodes (ace1=.2, ace2=.5, bee=.3, jet1=.4), dynamic range .50-.150, DNS-only disabled (`port=0`) |
| 6 | /etc/hosts | Adds `162.55.57.175 vpn.kubelab.live` for VPN bootstrap resilience |
| 7 | resolv.conf | Static `8.8.8.8` + `1.1.1.1` for first boot (Pi-hole takes over later) |
| 8 | Mask services | Disables `systemd-resolved` and `avahi-daemon` to avoid DNS conflicts |

## Procedure

```bash
# 1. Flash SD card with Raspberry Pi Imager (Ubuntu Server ARM64)
#    Set: hostname, user manu, WiFi creds, SSH enabled

# 2. Insert SD card into workstation, verify mount
ls /media/$USER/writable/etc

# 3. Run the script
cd ~/Projects/kubelab
sudo bash infra/provisioning/rpi4/configure-sd.sh

# 4. Eject SD card and insert into RPi4
```

## After First Boot

1. **Find the RPi4 IP** on your network:
   ```bash
   nmap -sn 10.0.0.0/24 | grep -B1 'E4:5F:01'
   ```

2. **SSH in and install required packages**:
   ```bash
   ssh manu@<IP>
   sudo apt update && sudo apt install -y nftables dnsmasq
   sudo systemctl enable nftables dnsmasq
   sudo reboot
   ```

3. **Run Ansible provisioning** (from workstation) for Docker, Tailscale, Pi-hole, CoreDNS:
   ```bash
   make provision-rpi4
   ```

## Related

- Script: `infra/provisioning/rpi4/configure-sd.sh`
- Network topology: vault `05-hardware/` and `04-infra/`
- DHCP static leases reference: `infra/config/values/common.yaml` (`networking.*`)
