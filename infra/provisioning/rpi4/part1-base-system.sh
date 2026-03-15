#!/usr/bin/env bash
# =============================================================================
# KubeLab RPi 4 Provisioning — Part 1: Base System
# =============================================================================
# Run as root after first SSH into a fresh Ubuntu Server 24.04 LTS arm64.
#
#   ssh manu@<IP>
#   sudo -i
#   bash part1-base-system.sh
#
# After completion: reboot, then run part2-services.sh as user manu.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOSTNAME="kubelab-rpi4"
USERNAME="manu"
LAN_IF="eth0"
LAN_IP="172.16.1.1"
LAN_NETMASK="255.255.255.0"
DHCP_RANGE_START="172.16.1.50"
DHCP_RANGE_END="172.16.1.150"
DHCP_LEASE="12h"
VPS_PUBLIC_IP="162.55.57.175"
HEADSCALE_DOMAIN="vpn.kubelab.live"

echo "=== KubeLab RPi 4 Provisioning — Part 1: Base System ==="
echo ""

# ---------------------------------------------------------------------------
# 1. Hostname
# ---------------------------------------------------------------------------
echo "[1/9] Setting hostname to ${HOSTNAME}..."
hostnamectl set-hostname "${HOSTNAME}"

if [ -f /etc/cloud/cloud.cfg ]; then
    sed -i 's/^preserve_hostname: false/preserve_hostname: true/' /etc/cloud/cloud.cfg 2>/dev/null || true
    grep -q "preserve_hostname: true" /etc/cloud/cloud.cfg || \
        echo "preserve_hostname: true" >> /etc/cloud/cloud.cfg
fi

sed -i "/127\.0\.1\.1/d" /etc/hosts
echo "127.0.1.1 ${HOSTNAME}" >> /etc/hosts

echo "  OK: hostname = $(hostname)"

# ---------------------------------------------------------------------------
# 2. User setup
# ---------------------------------------------------------------------------
echo "[2/9] Setting up user ${USERNAME}..."
if ! id "${USERNAME}" &>/dev/null; then
    adduser --disabled-password --gecos "" "${USERNAME}"
    usermod -aG sudo "${USERNAME}"
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-${USERNAME}-nopasswd"
    chmod 440 "/etc/sudoers.d/90-${USERNAME}-nopasswd"
    echo "  Created user ${USERNAME} with passwordless sudo"
else
    echo "  User ${USERNAME} already exists"
fi

if [ -d /home/ubuntu/.ssh ] && [ -f /home/ubuntu/.ssh/authorized_keys ]; then
    mkdir -p "/home/${USERNAME}/.ssh"
    cp /home/ubuntu/.ssh/authorized_keys "/home/${USERNAME}/.ssh/authorized_keys"
    chmod 700 "/home/${USERNAME}/.ssh"
    chmod 600 "/home/${USERNAME}/.ssh/authorized_keys"
    chown -R "${USERNAME}:${USERNAME}" "/home/${USERNAME}/.ssh"
    echo "  Copied SSH keys from ubuntu user"
fi

# ---------------------------------------------------------------------------
# 3. Disable cloud-init network config
# ---------------------------------------------------------------------------
echo "[3/9] Disabling cloud-init network management..."
mkdir -p /etc/cloud/cloud.cfg.d
cat > /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg <<'EOF'
network: {config: disabled}
EOF
echo "  OK: cloud-init network config disabled"

# ---------------------------------------------------------------------------
# 4. Netplan — 3 interfaces (USB ETH WAN, WiFi WAN backup, eth0 LAN)
# ---------------------------------------------------------------------------
echo "[4/9] Configuring netplan (3 interfaces)..."

rm -f /etc/netplan/50-cloud-init.yaml

cat > /etc/netplan/01-kubelab-gateway.yaml <<'EOF'
# KubeLab RPi 4 Gateway — Network Configuration
# USB Ethernet (enx*): WAN uplink to router, DHCP, metric 100 (primary)
# wlan0: WiFi WAN backup to router, DHCP, metric 600 (failover)
# eth0: LAN downlink to switch, static 172.16.1.1/24
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
      access-points:
        "REPLACE_WITH_SSID":
          password: "REPLACE_WITH_PASSWORD"
      optional: true
EOF

chmod 600 /etc/netplan/01-kubelab-gateway.yaml

echo "  IMPORTANT: Edit /etc/netplan/01-kubelab-gateway.yaml"
echo "  Replace REPLACE_WITH_SSID and REPLACE_WITH_PASSWORD with your WiFi credentials."
echo "  If RPi Imager already configured WiFi, you can skip this."

# ---------------------------------------------------------------------------
# 5. IP forwarding
# ---------------------------------------------------------------------------
echo "[5/9] Enabling IP forwarding..."
cat > /etc/sysctl.d/99-gateway.conf <<'EOF'
net.ipv4.ip_forward = 1
EOF
sysctl -p /etc/sysctl.d/99-gateway.conf
echo "  OK: net.ipv4.ip_forward = $(sysctl -n net.ipv4.ip_forward)"

# ---------------------------------------------------------------------------
# 6. nftables NAT masquerade
# ---------------------------------------------------------------------------
echo "[6/9] Configuring nftables NAT..."
apt-get update -qq && apt-get install -y -qq nftables > /dev/null 2>&1

cat > /etc/nftables.conf <<'EOF'
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
        # NAT: LAN (eth0) → WAN (USB Ethernet)
        # Wildcard enx* survives USB adapter replacement
        oifname "enx*" masquerade
    }
}
EOF

nft flush ruleset
nft -f /etc/nftables.conf
systemctl enable nftables
echo "  OK: nftables NAT active (enx* wildcard)"

# ---------------------------------------------------------------------------
# 7. dnsmasq DHCP server on eth0
# ---------------------------------------------------------------------------
echo "[7/9] Installing and configuring dnsmasq DHCP..."
apt-get install -y -qq dnsmasq > /dev/null 2>&1

cat > /etc/dnsmasq.d/kubelab-dhcp.conf <<EOF
# KubeLab DHCP server — RPi 4 gateway
# dnsmasq handles DHCP only (port 67). DNS is handled by Pi-hole (port 53).
port=0
interface=${LAN_IF}
bind-interfaces

dhcp-range=${DHCP_RANGE_START},${DHCP_RANGE_END},${LAN_NETMASK},${DHCP_LEASE}

# Gateway and DNS for clients
dhcp-option=option:router,${LAN_IP}
dhcp-option=option:dns-server,8.8.8.8,1.1.1.1

# Static reservations
dhcp-host=68:1D:EF:38:C5:6F,kubelab-ace1,172.16.1.2
dhcp-host=68:1D:EF:38:C5:8B,kubelab-ace2,172.16.1.5
dhcp-host=78:55:36:06:18:14,kubelab-bee,172.16.1.3
dhcp-host=00:04:4b:e5:5f:28,kubelab-jet1,172.16.1.4
EOF

systemctl enable dnsmasq
systemctl restart dnsmasq
echo "  OK: dnsmasq DHCP on ${LAN_IF}"

# ---------------------------------------------------------------------------
# 8. Disable avahi-daemon (frees port 5353 for CoreDNS)
# ---------------------------------------------------------------------------
echo "[8/9] Disabling avahi-daemon..."
systemctl disable --now avahi-daemon.socket 2>/dev/null || true
systemctl disable --now avahi-daemon 2>/dev/null || true
echo "  OK: avahi-daemon disabled"

# ---------------------------------------------------------------------------
# 9. /etc/hosts fallback + disable systemd-resolved
# ---------------------------------------------------------------------------
echo "[9/9] Configuring DNS fallback..."

systemctl stop systemd-resolved 2>/dev/null || true
systemctl disable systemd-resolved 2>/dev/null || true

rm -f /etc/resolv.conf
printf "nameserver 127.0.0.1\nnameserver 8.8.8.8\n" > /etc/resolv.conf

if ! grep -q "${VPS_PUBLIC_IP} ${HEADSCALE_DOMAIN}" /etc/hosts; then
    cat >> /etc/hosts <<EOF

# BEGIN KUBELAB DNS RESILIENCE
${VPS_PUBLIC_IP} ${HEADSCALE_DOMAIN}
# END KUBELAB DNS RESILIENCE
EOF
fi
echo "  OK: systemd-resolved disabled, /etc/hosts fallback added"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================="
echo "Part 1 complete."
echo "============================================="
echo "  Hostname:    ${HOSTNAME}"
echo "  User:        ${USERNAME} (passwordless sudo)"
echo "  LAN:         ${LAN_IF} = ${LAN_IP}/24"
echo "  WAN:         enx* (USB ETH, DHCP, metric 100)"
echo "  WiFi:        wlan0 (DHCP, metric 600)"
echo "  NAT:         enx* masquerade"
echo "  DHCP:        dnsmasq on ${LAN_IF}"
echo "  /etc/hosts:  ${VPS_PUBLIC_IP} ${HEADSCALE_DOMAIN}"
echo ""
echo "NEXT:"
echo "  1. Edit WiFi in /etc/netplan/01-kubelab-gateway.yaml (if not set via Imager)"
echo "  2. sudo netplan apply"
echo "  3. Verify: ping -c2 8.8.8.8"
echo "  4. sudo reboot"
echo "  5. SSH as manu, run part2-services.sh"
echo "============================================="
