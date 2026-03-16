#!/bin/bash
# Sets a static IP using Netplan.
# This script is the bootstrap step before full Ansible adoption.
#
# Usage: sudo ./set_static_netplan.sh <TARGET_IP>
# Later do: sudo chmod 600 /etc/netplan/99-static-config.yaml

if [ "$#" -ne 1 ]; then
    echo "Error: Missing required argument (Target IP Address)." >&2
    echo "Usage: sudo $0 <IP_ADDRESS>" >&2
    exit 1
fi

STATIC_IP="$1"
GATEWAY="192.168.2.1"
NETPLAN_FILE="/etc/netplan/99-static-config.yaml"

echo "Setting static IP: ${STATIC_IP}/24, Gateway: ${GATEWAY}"

# Write Netplan YAML using Heredoc
cat <<EOF > ${NETPLAN_FILE}
network:
    version: 2
    renderer: networkd
    ethernets:
        eth0:
            dhcp4: false
            addresses:
                - ${STATIC_IP}/24
            routes:
                - to: default
                  via: ${GATEWAY}
            nameservers:
                addresses: [1.1.1.1, 8.8.8.8]
EOF

# Apply Netplan configuration
echo "Applying Netplan configuration..."
# The 'netplan apply' command must be run with elevated privileges.
netplan apply

if [ $? -eq 0 ]; then
    echo "SUCCESS: Configuration applied. Static IP is now ${STATIC_IP}."
    ip addr show eth0
else
    echo "ERROR: netplan apply failed. Check YAML syntax in ${NETPLAN_FILE}."
fi
