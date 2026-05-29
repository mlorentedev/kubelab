---
id: rpi4-bootstrap
type: runbook
status: active
created: "2026-03-18"
owner: manu
---

# RPi4 Gateway Bootstrap (SD Card Recovery)

> Use when: SD card dies, RPi4 needs full rebuild from scratch.
> Time: ~20 min (flash + configure + provision)

## Prerequisites

- Micro SD card (32GB+ recommended)
- SD card reader on workstation
- Raspberry Pi Imager installed (`sudo apt install rpi-imager`)
- KubeLab repo cloned with Ansible roles available

## Step 1: Flash Ubuntu Server

1. Open Raspberry Pi Imager
2. **Device**: Raspberry Pi 4
3. **OS**: Other → Ubuntu Server 24.04 LTS (64-bit)
4. **Storage**: Select SD card
5. **Settings** (gear icon):
   - Hostname: `rpi4`
   - Username: `manu` / your password
   - WiFi: configure your home network (SSID + password)
   - Locale: your timezone
   - SSH: Enable with password authentication
6. Flash and wait

## Step 2: Configure SD Card (pre-boot)

Mount the SD card (two partitions appear: `system-boot` and `writable`).

### 2a. Netplan — Gateway networking

The RPi4 has 3 network interfaces:
- `eth0`: Homelab LAN (static 172.16.1.1/24) — connected to homelab switch
- `enx00249b1b0d6b`: USB Ethernet adapter (DHCP from router) — uplink to internet
- `wlan0`: WiFi (DHCP, fallback uplink)

```bash
WRITABLE="/media/$USER/writable"

# Extract WiFi credentials from Imager config
WIFI_SSID=$(awk '/access-points:/{getline; gsub(/^[[:space:]]+|":|:/,""); print; exit}' \
  "$WRITABLE/etc/netplan/50-cloud-init.yaml" | tr -d '"')
WIFI_PASS=$(awk '/password:/{print $2; exit}' \
  "$WRITABLE/etc/netplan/50-cloud-init.yaml" | tr -d '"')

echo "WiFi: $WIFI_SSID"

cat > "$WRITABLE/etc/netplan/01-kubelab-gateway.yaml" << EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      addresses:
        - 172.16.1.1/24
      nameservers:
        addresses: []
    enx00249b1b0d6b:
      dhcp4: true
      dhcp4-overrides:
        route-metric: 100
      optional: true
  wifis:
    wlan0:
      dhcp4: true
      dhcp4-overrides:
        route-metric: 600
      optional: true
      regulatory-domain: "ES"
      access-points:
        "${WIFI_SSID}":
          auth:
            key-management: "psk"
            password: "${WIFI_PASS}"
EOF

chmod 600 "$WRITABLE/etc/netplan/01-kubelab-gateway.yaml"
rm -f "$WRITABLE/etc/netplan/50-cloud-init.yaml"
```

### 2b. Disable cloud-init network management

```bash
mkdir -p "$WRITABLE/etc/cloud/cloud.cfg.d"
echo "network: {config: disabled}" > "$WRITABLE/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg"
sed -i 's/^preserve_hostname: false/preserve_hostname: true/' "$WRITABLE/etc/cloud/cloud.cfg" 2>/dev/null || true
```

### 2c. Static resolv.conf for first boot

```bash
rm -f "$WRITABLE/etc/resolv.conf"
printf "nameserver 8.8.8.8\nnameserver 1.1.1.1\n" > "$WRITABLE/etc/resolv.conf"
```

### 2d. Mask systemd-resolved and avahi

```bash
ln -sf /dev/null "$WRITABLE/etc/systemd/system/systemd-resolved.service"
ln -sf /dev/null "$WRITABLE/etc/systemd/system/avahi-daemon.service"
ln -sf /dev/null "$WRITABLE/etc/systemd/system/avahi-daemon.socket"
```

## Step 3: First Boot

1. Eject SD card, insert in RPi4, connect power + Ethernet cables
2. Wait ~2 minutes for first boot
3. Find the RPi4 IP on your home network:
   ```bash
   nmap -sn 10.0.0.0/24 | grep -B1 'E4:5F:01'
   # or check your router's DHCP leases
   ```
4. SSH in:
   ```bash
   ssh manu@<IP>
   ```

## Step 4: Ansible Provisioning

From your workstation, in the kubelab repo:

```bash
# This installs: gateway networking (nftables, dnsmasq, IP forwarding),
# Docker, Tailscale, CoreDNS, Pi-hole, SSH hardening, base packages
make provision NODE=rpi4 ENV=prod
```

**Note**: Tailscale registration requires a pre-auth key from Headscale. If no key is provided, the playbook will print manual instructions.

Generate a key on VPS:
```bash
ssh kubelab-vps 'docker exec headscale headscale preauthkeys create --user 2 --expiration 1h'
```

## Step 5: Post-Provisioning

1. **Verify gateway routing**: from a homelab node (ace1/ace2), check internet access
2. **Verify DNS**: `dig @172.16.1.1 api.staging.kubelab.live` should resolve
3. **Verify Tailscale**: `tailscale status` on RPi4 should show mesh
4. **Approve Tailscale routes** on Headscale:
   ```bash
   ssh kubelab-vps 'docker exec headscale headscale routes list'
   ssh kubelab-vps 'docker exec headscale headscale routes enable -r <route-id>'
   ```
5. **Update SSH config**: if Tailscale IP changed, update `~/.ssh/config`

## Hardware Notes

- **USB Ethernet adapter MAC**: `enx00249b1b0d6b` (the interface name IS the MAC)
- **RPi4 WiFi MAC**: starts with `E4:5F:01`
- **eth0**: built-in Ethernet, connects to homelab switch
- **Power**: USB-C, 5V/3A minimum. Use official PSU to avoid undervoltage.

## DHCP Reservations

Managed by Ansible (gateway role). Current reservations:

| Device | MAC | IP |
|--------|-----|-----|
| ace1 | 68:1D:EF:38:C5:6F | 172.16.1.2 |
| ace2 | 68:1D:EF:38:C5:8B | 172.16.1.5 |
| beelink | 78:55:36:06:18:14 | 172.16.1.3 |
| jetson | 00:04:4b:e5:5f:28 | 172.16.1.4 |
