#!/bin/sh
# Says, after a boot, whether the edge brought back everything it serves (NET-005
# AC13; the hard-reset test in docs/runbooks/lab-edge.md). `make edge-boot-check`
# runs it over SSH. It reads and changes nothing. It uses `sudo -n` only where a
# read needs root: the ruleset, the containers, hostapd's socket and the tailnet.
#
# Usage: kubelab-edge-boot-check <lan if> <lan address> <uplink if> <ap if> <lan cidr>
#
# EDGE_EXPECT names what the case under test took away: `no-uplink` (the adapter
# unplugged) or `no-lan` (the switch cable out). The check for that thing then
# passes when it is missing, and the checks that need it are not run.
#
# Exit codes:
#   0   every check passed
#   1   one or more failed
#   64  usage
#
# One line per check, and no host address, MAC or key: the output lands in a spec's
# evidence. The LAN CIDR it names is declared in the public common.yaml.
# shellcheck disable=SC2329 # each probe runs through check or missing
set -u

usage() {
  echo "usage: $(basename "$0") <lan if> <lan address> <uplink if> <ap if> <lan cidr>" >&2
  exit 64
}

[ $# -eq 5 ] || usage
lan=$1
lan_address=$2
uplink=$3
ap=$4
lan_cidr=$5
expect=${EDGE_EXPECT:-}
case $expect in '' | no-uplink | no-lan) ;; *) usage ;; esac
sys_net=${EDGE_SYS_NET:-/sys/class/net}
hostapd_dir=${EDGE_HOSTAPD_DIR:-/run/hostapd}
failed=0

pass() { echo "OK   $1"; }
fail() {
  echo "FAIL $1"
  failed=1
}

# check <name> <command...>: the command's status decides.
check() {
  name=$1
  shift
  if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi
}

# missing <name> <command...>: the case took it away, so the command must fail.
missing() {
  name=$1
  shift
  if "$@" >/dev/null 2>&1; then
    fail "$name: present, but this case took it away"
  else
    pass "$name: missing, as this case expects"
  fi
}

# The uplink's drops must be loaded before it can have an address (AC3), at boot
# too. It has none until systemd-networkd configures it: the role disables IPv6
# on it when the device appears. The order comes from systemd's own record of
# the boot, in microseconds since boot, because the journal can lose a boot's
# first seconds to its size cap. The role only ever reloads the ruleset, which
# keeps the timestamp. A restart of either unit moves it, by hand or by an
# unattended upgrade, so the check is for a boot nothing has restarted since.
since_boot() { systemctl show -p "$1" --value "$2"; }
loaded=$(since_boot ActiveEnterTimestampMonotonic nftables.service)
networkd=$(since_boot InactiveExitTimestampMonotonic systemd-networkd.service)
drops_first() { [ "${loaded:-0}" -gt 0 ] && [ "$loaded" -lt "${networkd:-0}" ]; }
seconds() { awk -v usec="${1:-0}" 'BEGIN { printf "%.1fs", usec / 1000000 }'; }

has_carrier() { [ "$(cat "$sys_net/$1/carrier" 2>/dev/null)" = 1 ]; }
# Unplugged, not gone: only a device that is there reports a carrier of 0.
unplugged() { [ "$(cat "$sys_net/$1/carrier" 2>/dev/null)" = 0 ]; }
lan_address_set() { ip -4 -o addr show dev "$lan" | grep -q " $lan_address/"; }
uplink_lease() { ip -4 -o addr show dev "$uplink" scope global | grep -q ' inet '; }
default_route() { ip -4 route show default dev "$uplink" | grep -q '^default'; }
# hostapd reports ENABLED once the AP beacons, not when the radio is merely in AP mode.
serves_ap() { sudo -n hostapd_cli -p "$hostapd_dir" -i "$ap" status | grep -qx 'state=ENABLED'; }
dhcp_listening() { ss -H -lun 'sport = :67' | grep -q .; }
# Pi-hole answers `localhost` from its own tables: this proves its port on the LAN
# address answers. Its healthcheck proves the hop to CoreDNS behind it.
lan_dns() { dig @"$lan_address" localhost +short +time=2 +tries=1 | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; }

# Running, and healthy when the image declares a health check.
container_up() {
  case $(sudo -n docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$1") in
    'running ' | 'running healthy') return 0 ;;
  esac
  return 1
}

# This node only: with peers, another node's routes would answer for it.
tailnet() { sudo -n tailscale status --json --peers=false | tr -d ' \t\n'; }
tailnet_up() { tailnet | grep -q '"BackendState":"Running"'; }
advertises_lan() { tailnet | grep -q "\"PrimaryRoutes\":\[[^]]*\"$lan_cidr\""; }

# Its timer runs it again every minute, and while a run is under way the unit is
# activating, not failed: wait that run out, for at most two minutes.
pages() {
  tries=0
  while [ "$(systemctl is-active "$1")" = activating ] && [ "$tries" -lt 60 ]; do
    sleep 2
    tries=$((tries + 1))
  done
  systemctl is-failed --quiet "$1"
}

watchdog_armed() {
  usec=$(systemctl show -p RuntimeWatchdogUSec --value)
  [ -n "$usec" ] && [ "$usec" != 0 ]
}

echo "INFO $(systemd-analyze time 2>/dev/null | head -n 1)"
echo "INFO ruleset loaded at $(seconds "$loaded"), systemd-networkd started at $(seconds "$networkd")"

check "ruleset inet kubelab loaded" sudo -n nft list table inet kubelab
check "ruleset loaded before systemd-networkd started" drops_first
check "hardware watchdog armed" watchdog_armed
for unit in hostapd.service dnsmasq.service docker.service tailscaled.service \
  kubelab-edge-liveness.timer kubelab-edge-lease-check.timer kubelab-edge-lease-check.path; do
  check "$unit active" systemctl is-active --quiet "$unit"
done
check "DHCP server listening" dhcp_listening
check "$ap serves the lab Wi-Fi" serves_ap
check "container coredns up" container_up coredns
check "container pihole up" container_up pihole

if [ "$expect" = no-lan ]; then
  check "$lan present without a carrier, as this case expects" unplugged "$lan"
else
  check "LAN address on $lan" lan_address_set
  check "DNS answers on the LAN address" lan_dns
fi

# The liveness check fails on a missing uplink, and the page its failure sends
# fails too: the edge has no route out. In that case both are expected, the page
# by the name systemd resolved from the unit's own OnFailure= line.
reporter=kubelab-edge-liveness.service
expected=
if [ "$expect" = no-uplink ]; then
  missing "uplink adapter $uplink" test -e "$sys_net/$uplink"
  check "$reporter failed on the missing uplink" pages "$reporter"
  expected="$reporter $(systemctl show -p OnFailure --value "$reporter")"
else
  check "lease on $uplink" uplink_lease
  check "default route out $uplink" default_route
  check "kubelab-edge-shaper.service active" systemctl is-active --quiet kubelab-edge-shaper.service
  check "tailnet session running" tailnet_up
  check "subnet route $lan_cidr primary on the tailnet" advertises_lan
fi

failed_units=$(systemctl --failed --no-legend --plain | awk -v expected="$expected" '
  BEGIN { n = split(expected, e, " "); for (i = 1; i <= n; i++) skip[e[i]] = 1 }
  !($1 in skip) { printf "%s%s", sep, $1; sep = " " }')
if [ -z "$failed_units" ]; then pass "no failed unit"; else fail "failed units: $failed_units"; fi

exit "$failed"
