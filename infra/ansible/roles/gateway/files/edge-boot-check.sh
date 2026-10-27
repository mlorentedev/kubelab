#!/bin/sh
# Says, after a boot, whether the edge brought back everything it serves (NET-005
# AC13; the hard-reset test in docs/runbooks/lab-edge.md). `make edge-boot-check`
# runs it over SSH. It reads and changes nothing. It uses `sudo -n` only where a
# read needs root: the ruleset, the system journal, the containers and the tailnet.
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

# Microseconds since boot of a unit's first journal line this boot that matches.
first_usec() {
  sudo -n journalctl -b -o short-monotonic --no-pager -u "$1" --grep "$2" 2>/dev/null |
    sed -n 's/^\[ *\([0-9]*\)\.\([0-9]\{6\}\)\].*/\1\2/p' | head -n 1
}

# The uplink's drops must be loaded before it has a carrier (AC3), at boot too.
drops_first() {
  loaded=$(first_usec nftables.service '^Finished')
  carrier=$(first_usec systemd-networkd.service "^$uplink: Gained carrier")
  [ -n "$loaded" ] && [ -n "$carrier" ] && [ "$loaded" -lt "$carrier" ]
}

has_carrier() { [ "$(cat "$sys_net/$1/carrier" 2>/dev/null)" = 1 ]; }
lan_address_set() { ip -4 -o addr show dev "$lan" | grep -q " $lan_address/"; }
uplink_lease() { ip -4 -o addr show dev "$uplink" scope global | grep -q ' inet '; }
default_route() { ip -4 route show default dev "$uplink" | grep -q '^default'; }
serves_ap() { iw dev "$ap" info | grep -q 'type AP'; }

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

watchdog_armed() {
  usec=$(systemctl show -p RuntimeWatchdogUSec --value)
  [ -n "$usec" ] && [ "$usec" != 0 ]
}

echo "INFO $(systemd-analyze time 2>/dev/null | head -n 1)"

check "ruleset inet kubelab loaded" sudo -n nft list table inet kubelab
check "hardware watchdog armed" watchdog_armed
for unit in hostapd.service dnsmasq.service docker.service tailscaled.service \
  kubelab-edge-liveness.timer kubelab-edge-lease-check.timer kubelab-edge-lease-check.path; do
  check "$unit active" systemctl is-active --quiet "$unit"
done
check "$ap serves the lab Wi-Fi" serves_ap
check "container coredns up" container_up coredns
check "container pihole up" container_up pihole

if [ "$expect" = no-lan ]; then
  missing "carrier on $lan" has_carrier "$lan"
else
  check "LAN address on $lan" lan_address_set
fi

# The liveness check pages a missing uplink: in that case its failure is the page.
reporter=kubelab-edge-liveness.service
if [ "$expect" = no-uplink ]; then
  missing "uplink adapter $uplink" test -e "$sys_net/$uplink"
  check "$reporter pages the missing uplink" systemctl is-failed --quiet "$reporter"
else
  check "drops loaded before $uplink had a carrier" drops_first
  check "lease on $uplink" uplink_lease
  check "default route out $uplink" default_route
  check "kubelab-edge-shaper.service active" systemctl is-active --quiet kubelab-edge-shaper.service
  check "tailnet session running" tailnet_up
  check "subnet route $lan_cidr primary on the tailnet" advertises_lan
  reporter=
fi

failed_units=$(systemctl --failed --no-legend --plain | awk -v skip="$reporter" '$1 != skip { printf "%s%s", sep, $1; sep = " " }')
if [ -z "$failed_units" ]; then pass "no failed unit"; else fail "failed units: $failed_units"; fi

exit "$failed"
