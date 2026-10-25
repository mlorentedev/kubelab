---
id: rpi4-bootstrap
type: runbook
status: active
created: "2026-03-18"
owner: manu
---

# RPi4 Edge Bootstrap (SD Card Recovery)

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
   - Username: `manu`, with your SSH public key
   - **No Wi-Fi.** The built-in radio is the lab's access point (ADR-075 D2), and Imager would write the network's PSK to the card in clear.
   - Locale: your timezone
6. Flash and wait

## Step 2: Configure SD Card (pre-boot)

Mount the SD card (two partitions appear: `system-boot` and `writable`).

### 2a. Netplan: the LAN only

The card needs one thing from the network config: `eth0` on the edge's LAN address, so a laptop on the switch can reach it. The first provision renders the rest, the uplink included, into the same file (ADR-075 D2, `networking.edge.uplink`), and moves any other netplan file to `/var/backups/kubelab-netplan/`.

```bash
WRITABLE="/media/$USER/writable"

# 172.16.1.1/24 is networking.nodes.rpi4.lan_ip in networking.lan_cidr (common.yaml).
sudo install -m 600 /dev/stdin "$WRITABLE/etc/netplan/10-kubelab-edge.yaml" << 'EOF'
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      addresses: [172.16.1.1/24]
EOF

sudo rm -f "$WRITABLE/etc/netplan/50-cloud-init.yaml"
```

The same file recovers an edge whose profile cut the LAN ([lab-edge](lab-edge.md#when-a-profile-cuts-the-lan)).

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

1. Eject the SD card, insert it in the RPi4, plug in the adapters (the uplink adapter on a USB 2.0 port with its extension cable, `eth0` to the switch) and power it.
2. Wait ~2 minutes for first boot.
3. From the laptop on the switch, join the LAN with a fixed address, since the edge serves no DHCP yet:

   ```bash
   make edge-lan-link STATIC=1
   ```

## Step 4: Ansible Provisioning

Over the LAN, never the tailnet, in the order of [lab-edge](lab-edge.md#moving-to-a-new-site):

```bash
make provision NODE=rpi4 ENV=prod BOOTSTRAP=1 TAGS=gateway
make edge-status
```

At a captive-portal site, log in as [lab-edge](lab-edge.md#captive-portal) describes, then finish the provision and join the mesh:

```bash
make provision NODE=rpi4 ENV=prod BOOTSTRAP=1
make headscale-rejoin NODE=rpi4
make edge-lan-link
```

The last line moves the laptop back to a DHCP lease, which the edge now serves.

**Known gap (#2680):** the `gateway` role installs `dnsmasq` before it renders the uplink, and a fresh image may not carry it. If the first run fails installing the gateway packages, the archive is unreachable because the uplink does not exist yet.

## Step 5: Post-Provisioning

1. **Verify the uplink**: `make edge-status` reports `up`.
2. **Verify the homelab**: with the homelab powered, `make test-e2e ENV=staging` passes.
3. **Approve the subnet route** on Headscale. A fresh SD card registers a new node, and its `networking.lan_cidr` route needs approval: today a Headscale command ([headscale-setup](headscale-setup.md)), with no target yet (#2678).

## Hardware Notes

- **Uplink adapter**: named `uplink0` by the `gateway` role, matched by the MAC in SOPS (`networking.edge.uplink.mac`). The kernel's own name for it carries the MAC, so no runbook names it (ADR-075 C7).
- **eth0**: built-in Ethernet, connects to the homelab switch.
- **wlan0**: built-in radio, the lab Wi-Fi's access point.
- **Power**: USB-C, 5V/3A minimum. Use the official PSU to avoid undervoltage.

## DHCP Reservations

Managed by Ansible (`gateway` role), from the SSOT: each node's `networking.nodes.<node>.mac` and `lan_ip` in `infra/config/values/common.yaml`. The lab Wi-Fi's reservations are `networking.edge.lab_wifi.reservations`.
