#!/usr/bin/env bash
# =============================================================================
# KubeLab RPi 4 — Pre-configure SD card before first boot
# =============================================================================
# Run from workstation with SD card mounted at /media/$USER/writable
#
#   sudo bash configure-sd.sh
# =============================================================================
set -euo pipefail

WRITABLE="/media/manu/writable"
BOOT="/media/manu/system-boot"

if [ ! -d "$WRITABLE/etc" ]; then
    echo "ERROR: $WRITABLE/etc not found. Is the SD card mounted?"
    exit 1
fi

echo "=== Configuring RPi4 SD card ==="

# ---------------------------------------------------------------------------
# 1. Netplan — 3 interfaces (preserve WiFi creds from Imager)
# ---------------------------------------------------------------------------
echo "[1/8] Netplan..."

# Extract WiFi credentials from Imager config
# SSID is the line directly under "access-points:" — extract the key name
WIFI_SSID=$(awk '/access-points:/{getline; gsub(/^[[:space:]]+|":|:/,""); print; exit}' "$WRITABLE/etc/netplan/50-cloud-init.yaml" | tr -d '"')
WIFI_PASS=$(awk '/password:/{print $2; exit}' "$WRITABLE/etc/netplan/50-cloud-init.yaml" | tr -d '"')

if [ -z "$WIFI_SSID" ] || [ -z "$WIFI_PASS" ]; then
    echo "  WARNING: Could not extract WiFi credentials from Imager config."
    echo "  Edit /etc/netplan/01-kubelab-gateway.yaml manually after boot."
    WIFI_SSID="REPLACE_WITH_SSID"
    WIFI_PASS="REPLACE_WITH_PASSWORD"
fi
echo "  WiFi SSID: ${WIFI_SSID}"

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
echo "  OK"

# ---------------------------------------------------------------------------
# 2. Disable cloud-init network management
# ---------------------------------------------------------------------------
echo "[2/8] Cloud-init disable..."
mkdir -p "$WRITABLE/etc/cloud/cloud.cfg.d"
echo "network: {config: disabled}" > "$WRITABLE/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg"

if [ -f "$WRITABLE/etc/cloud/cloud.cfg" ]; then
    sed -i 's/^preserve_hostname: false/preserve_hostname: true/' "$WRITABLE/etc/cloud/cloud.cfg"
fi
echo "  OK"

# ---------------------------------------------------------------------------
# 3. IP forwarding
# ---------------------------------------------------------------------------
echo "[3/8] IP forwarding..."
cat > "$WRITABLE/etc/sysctl.d/99-gateway.conf" << 'EOF'
net.ipv4.ip_forward = 1
EOF
echo "  OK"

# ---------------------------------------------------------------------------
# 4. nftables NAT
# ---------------------------------------------------------------------------
echo "[4/8] nftables NAT..."
cat > "$WRITABLE/etc/nftables.conf" << 'EOF'
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input { type filter hook input priority 0; policy accept; }
    chain forward { type filter hook forward priority 0; policy accept; }
    chain output { type filter hook output priority 0; policy accept; }
}

table inet nat {
    chain postrouting {
        type nat hook postrouting priority 100; policy accept;
        oifname "enx*" masquerade
    }
}
EOF
echo "  OK"

# ---------------------------------------------------------------------------
# 5. dnsmasq DHCP config
# ---------------------------------------------------------------------------
echo "[5/8] dnsmasq DHCP config..."
mkdir -p "$WRITABLE/etc/dnsmasq.d"
cat > "$WRITABLE/etc/dnsmasq.d/kubelab-dhcp.conf" << 'EOF'
port=0
interface=eth0
bind-interfaces

dhcp-range=172.16.1.50,172.16.1.150,255.255.255.0,12h

dhcp-option=option:router,172.16.1.1
dhcp-option=option:dns-server,8.8.8.8,1.1.1.1

dhcp-host=68:1D:EF:38:C5:6F,kubelab-ace1,172.16.1.2
dhcp-host=68:1D:EF:38:C5:8B,kubelab-ace2,172.16.1.5
dhcp-host=78:55:36:06:18:14,kubelab-bee,172.16.1.3
dhcp-host=00:04:4b:e5:5f:28,kubelab-jet1,172.16.1.4
EOF
echo "  OK"

# ---------------------------------------------------------------------------
# 6. /etc/hosts — VPN bootstrap fallback
# ---------------------------------------------------------------------------
echo "[6/8] /etc/hosts fallback..."
if ! grep -q "162.55.57.175 vpn.kubelab.live" "$WRITABLE/etc/hosts"; then
    cat >> "$WRITABLE/etc/hosts" << 'EOF'

# BEGIN KUBELAB DNS RESILIENCE
162.55.57.175 vpn.kubelab.live
# END KUBELAB DNS RESILIENCE
EOF
fi
echo "  OK"

# ---------------------------------------------------------------------------
# 7. resolv.conf (static, will be locked by part2)
# ---------------------------------------------------------------------------
echo "[7/8] resolv.conf..."
rm -f "$WRITABLE/etc/resolv.conf"
printf "nameserver 8.8.8.8\nnameserver 1.1.1.1\n" > "$WRITABLE/etc/resolv.conf"
echo "  OK (8.8.8.8 for first boot, part2 switches to Pi-hole)"

# ---------------------------------------------------------------------------
# 8. Disable systemd-resolved and avahi (will take effect on boot)
# ---------------------------------------------------------------------------
echo "[8/8] Disable systemd-resolved + avahi..."
# Mask services so they don't start on boot
ln -sf /dev/null "$WRITABLE/etc/systemd/system/systemd-resolved.service" 2>/dev/null || true
ln -sf /dev/null "$WRITABLE/etc/systemd/system/avahi-daemon.service" 2>/dev/null || true
ln -sf /dev/null "$WRITABLE/etc/systemd/system/avahi-daemon.socket" 2>/dev/null || true
echo "  OK"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================="
echo "SD card configured. Safe to eject."
echo "============================================="
echo ""
echo "After booting RPi4:"
echo "  1. Find IP:  nmap -sn 10.0.0.0/24 | grep -B1 'E4:5F:01'"
echo "  2. SSH:      ssh manu@<IP>"
echo "  3. Install:  sudo apt update && sudo apt install -y nftables dnsmasq"
echo "  4. Enable:   sudo systemctl enable nftables dnsmasq"
echo "  5. Reboot:   sudo reboot"
echo "  6. Run:      bash part2-services.sh (Docker, Tailscale, Pi-hole, CoreDNS)"
echo "============================================="
