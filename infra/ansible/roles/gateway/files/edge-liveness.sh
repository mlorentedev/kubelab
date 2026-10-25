#!/bin/sh
# Checks the lab Wi-Fi and the uplink, and brings a halted radio back (NET-005
# AC13, ADR-075 D5). kubelab-edge-liveness.timer runs it every minute, and a
# non-zero exit pages through OnFailure=.
#
# Usage: kubelab-edge-liveness <ap interface> <ap driver> <uplink interface>
#
# Exit codes:
#   0   both serve, or a miss still inside the grace
#   1   a component is failing: the lab Wi-Fi past the grace, or the uplink
#   64  usage
#
# The lab Wi-Fi serves when its interface is up and hostapd reports ENABLED. The
# RPi4's radio firmware can halt (raspberrypi/firmware#1403), and only a reboot is
# known to bring it back, so the ladder is:
#
#   1. fewer than EDGE_LIVENESS_GRACE misses in a row: log only, since a provision
#      restarts hostapd;
#   2. the grace-th miss: unload the driver with whatever holds it, load it again,
#      and restart hostapd;
#   3. the next miss: reboot, unless the edge already rebooted
#      EDGE_LIVENESS_MAX_REBOOTS times in the last hour, in which case it holds and
#      keeps paging. A radio that never comes back cannot loop the edge.
#
# The misses and the reload marker live in RUNTIME_DIRECTORY, so a reboot starts the
# ladder again. The reboots are counted in STATE_DIRECTORY, which a reboot keeps.
# The RPi4 has no RTC and boots with a stale clock until NTP answers, so a reboot
# recorded later than now counts as recent: a clock that went back must not lift
# the cap.
#
# The uplink is reported, never rebooted for. A present adapter with no lease is
# the site (down, out of range, a changed passphrase), which a reboot cannot fix,
# and the reboot would take the lab Wi-Fi, rpi3 and the homelab's route with it.
# An adapter that disappeared gets its driver reloaded once per incident; an
# unplugged one looks the same, so the edge does no more than that.
set -u

usage() {
  echo "usage: $(basename "$0") <ap interface> <ap driver> <uplink interface>" >&2
  exit 64
}

[ $# -eq 3 ] || usage
ap=$1
ap_driver=$2
uplink=$3
grace=${EDGE_LIVENESS_GRACE:-3}
max_reboots=${EDGE_LIVENESS_MAX_REBOOTS:-2}
for value in "$grace" "$max_reboots"; do
  case $value in '' | *[!0-9]* | 0) usage ;; esac
done
run_dir=${RUNTIME_DIRECTORY:?set by RuntimeDirectory= in the unit}
state_dir=${STATE_DIRECTORY:?set by StateDirectory= in the unit}
sys_net=${EDGE_SYS_NET:-/sys/class/net}
sys_module=${EDGE_SYS_MODULE:-/sys/module}
leases_dir=${EDGE_LEASES_DIR:-/run/systemd/netif/leases}
hostapd_dir=${EDGE_HOSTAPD_DIR:-/run/hostapd}
now=${EDGE_NOW:-$(date +%s)}
settle=${EDGE_SETTLE:-30}
window=3600

# Counts one more miss for a component and prints the count.
miss() {
  count=$(cat "$run_dir/$1.misses" 2>/dev/null)
  case $count in '' | *[!0-9]*) count=0 ;; esac
  count=$((count + 1))
  echo "$count" >"$run_dir/$1.misses"
  echo "$count"
}

forget() {
  rm -f "$run_dir/$1.misses" "$run_dir/$1.reloaded"
}

# Unloads a module with every module that holds it, then loads it again. The
# vendor module (brcmfmac_wcc on the RPi4) holds brcmfmac, so removing it alone
# fails; loading brcmfmac requests the vendor module again.
reload_module() {
  holders=
  for holder in "$sys_module/$1/holders"/*; do
    [ -e "$holder" ] && holders="$holders ${holder##*/}"
  done
  # shellcheck disable=SC2086 # module names, split on purpose
  modprobe -r $holders "$1" || echo "could not unload $1; loading it anyway" >&2
  modprobe "$1"
}

ap_serving() {
  [ "$(cat "$sys_net/$ap/operstate" 2>/dev/null)" = up ] || return 1
  timeout 10 hostapd_cli -p "$hostapd_dir" -i "$ap" status 2>/dev/null | grep -qx 'state=ENABLED'
}

# Prunes the reboots older than the window and says whether one more fits.
reboot_allowed() {
  recent=0
  kept=
  if [ -f "$state_dir/reboots" ]; then
    while read -r at; do
      case $at in '' | *[!0-9]*) continue ;; esac
      if [ "$at" -gt $((now - window)) ]; then
        recent=$((recent + 1))
        kept="$kept$at
"
      fi
    done <"$state_dir/reboots"
  fi
  printf '%s' "$kept" >"$state_dir/reboots"
  [ "$recent" -lt "$max_reboots" ]
}

recover_ap() {
  misses=$(miss ap)
  if [ "$misses" -lt "$grace" ]; then
    echo "lab Wi-Fi: $ap is not serving ($misses of $grace misses before a driver reload)" >&2
    return 0
  fi
  if [ ! -e "$run_dir/ap.reloaded" ]; then
    echo "lab Wi-Fi: $ap has not served for $misses checks; reloading $ap_driver and restarting hostapd" >&2
    : >"$run_dir/ap.reloaded"
    reload_module "$ap_driver"
    waited=0
    while [ ! -e "$sys_net/$ap" ] && [ "$waited" -lt "$settle" ]; do
      sleep 1
      waited=$((waited + 1))
    done
    systemctl restart hostapd
    return 1
  fi
  if reboot_allowed; then
    echo "lab Wi-Fi: $ap is still not serving after the driver reload; rebooting the edge" >&2
    echo "$now" >>"$state_dir/reboots"
    systemctl reboot
    return 1
  fi
  echo "lab Wi-Fi: $ap is still not serving, and the edge already rebooted $max_reboots times in the last hour; holding the reboot until a human looks" >&2
  return 1
}

check_uplink() {
  device=$sys_net/$uplink
  if [ -e "$device" ]; then
    module=$(readlink "$device/device/driver/module" 2>/dev/null) && echo "${module##*/}" >"$run_dir/uplink.module"
    ifindex=$(cat "$device/ifindex" 2>/dev/null)
    if [ -n "$ifindex" ] && grep -q '^ADDRESS=' "$leases_dir/$ifindex" 2>/dev/null; then
      forget uplink
      return 0
    fi
    misses=$(miss uplink)
    [ "$misses" -lt "$grace" ] && return 0
    echo "uplink: $uplink has held no DHCP lease for $misses checks. The site's network is down, out of range or refusing the adapter; a reboot cannot fix that, so the edge does not try" >&2
    return 1
  fi
  misses=$(miss uplink)
  [ "$misses" -lt "$grace" ] && return 0
  if [ ! -e "$run_dir/uplink.reloaded" ] && [ -s "$run_dir/uplink.module" ]; then
    module=$(cat "$run_dir/uplink.module")
    : >"$run_dir/uplink.reloaded"
    echo "uplink: $uplink disappeared; reloading $module once" >&2
    reload_module "$module"
    return 1
  fi
  echo "uplink: $uplink is gone: unplugged, or its driver did not bring it back" >&2
  return 1
}

status=0
# The uplink first, so its driver is on record before a reboot.
check_uplink || status=1
if ap_serving; then
  forget ap
else
  recover_ap || status=1
fi
exit "$status"
