#!/bin/bash
# Temporary script to configure local SSH ProxyJump

# --- VARIABLES (Ensure these match your inventory) ---
PVE_IP_WAN="10.0.0.187"
RPI_STORAGE_IP="192.168.2.52"
RPI_APPS_IP="192.168.2.101"
SSH_KEY_PATH="~/.ssh/id_ed25519"

# Markers for idempotency
MARKER_START="# --- CUBELAB-SSH-START ---"
MARKER_END="# --- CUBELAB-SSH-END ---"
CONFIG_FILE="$HOME/.ssh/config"

echo "Configuring $CONFIG_FILE for the CubeLab cluster..."

# 1. Remove previous block if it exists
# The 'd' option in sed deletes lines between the markers.
sed -i.bak "/$MARKER_START/,/$MARKER_END/d" "$CONFIG_FILE"

# 2. Create and append the new idempotent block
cat <<EOF >> "$CONFIG_FILE"

$MARKER_START
# 1. Gateway/Jump Host (Proxmox)
Host pve
  Hostname $PVE_IP_WAN
  User root
  IdentityFile $SSH_KEY_PATH

# 2. ARM Nodes (Jumping via Proxmox)
Host rpi-storage
  Hostname $RPI_STORAGE_IP
  User pi
  ProxyJump pve
  IdentityFile $SSH_KEY_PATH

Host rpi-apps
  Hostname $RPI_APPS_IP
  User pi
  ProxyJump pve
  IdentityFile $SSH_KEY_PATH
$MARKER_END
EOF

echo "Configuration of ProxyJump completed in $CONFIG_FILE."
echo "You can now use 'ssh rpi-storage' and 'ssh rpi-apps'."
