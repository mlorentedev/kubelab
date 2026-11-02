#!/bin/sh
# Puts back the netplan a run replaced. The role arms `restore` on a timer before
# it writes anything and stops the timer once the node answers again, so a netplan
# that cuts the node off undoes itself. `restore` runs with no session attached.
set -eu
NETPLAN_DIR=${NETPLAN_DIR:-/etc/netplan}
BACKUP=${NETPLAN_BACKUP:-/var/backups/kubelab-netplan}

case "${1:-}" in
backup)
  systemctl stop kubelab-netplan-revert.timer 2>/dev/null || true
  systemctl reset-failed kubelab-netplan-revert.service 2>/dev/null || true
  rm -rf "$BACKUP"
  mkdir -p "$BACKUP"
  cp -a "$NETPLAN_DIR"/. "$BACKUP"/
  ;;
restore)
  [ -n "$(ls -A "$BACKUP")" ]
  find "$NETPLAN_DIR" -maxdepth 1 -type f \( -name '*.yaml' -o -name '*.yml' \) -delete
  cp -a "$BACKUP"/. "$NETPLAN_DIR"/
  netplan apply
  ;;
*)
  echo "usage: $0 backup|restore" >&2
  exit 2
  ;;
esac
