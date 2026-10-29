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
# passes when it is missing, and the checks that need it are not run. The LAN
# address needs only the device, not the cable (#2732), so `no-lan` keeps them.
#
# Exit codes:
#   0   every check passed
#   1   one or more failed
#   2   none failed, but one cannot be judged yet: run it again after the
#       minutes its WAIT line names
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
liveness_dir=${EDGE_LIVENESS_DIR:-/run/kubelab-edge-liveness}
uptime_file=${EDGE_UPTIME:-/proc/uptime}
failed=0
pending=0

pass() { echo "OK   $1"; }
fail() {
  echo "FAIL $1"
  failed=1
}
wait_for() {
  echo "WAIT $1"
  pending=1
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
# Without it, traffic for the LAN takes the default route out of the uplink.
lan_route() { ip -4 route show exact "$lan_cidr" dev "$lan" | awk -v cidr="$lan_cidr" '$1 == cidr { found = 1 } END { exit !found }'; }
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

# A start that failed on a bind leaves the container on no network: ports
# requested, none in effect, and dockerd restores it so at every boot (#2732).
# Both containers checked here publish ports, so none requested is a mapping
# dropped from the compose, not a container with nothing to publish.
ports_in_effect() {
  case $(sudo -n docker inspect -f '{{len .HostConfig.PortBindings}}:{{len .NetworkSettings.Ports}}' "$1") in
    '' | 0:* | [1-9]*:0) return 1 ;;
  esac
  return 0
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

# The liveness check tolerates a missing uplink for EDGE_LIVENESS_GRACE misses in a
# row, a minute apart, and its timer first runs minutes after boot. Until the last
# of those runs, an edge without its uplink is behaving as designed (#2774). Prints
# how long to wait, from the misses counted, the grace in the unit's own
# environment and, before its first run, the timer's schedule in microseconds
# since boot. A grace it cannot read, or a run that never ended ($1, the polls
# `pages` made of the reporter), is not waited for.
liveness_pending() {
  [ "$1" -lt 60 ] || return 1
  grace=$(systemctl show -p Environment --value "$reporter" | tr ' ' '\n' | sed -n 's/^EDGE_LIVENESS_GRACE=//p')
  case $grace in '' | *[!0-9]* | 0) return 1 ;; esac
  misses=$(cat "$liveness_dir/uplink.misses" 2>/dev/null)
  case $misses in '' | *[!0-9]*) misses=0 ;; esac
  [ "$misses" -lt "$grace" ] || return 1
  # One run a minute until the grace-th miss; the first run counts the first.
  left=$((grace - misses))
  if [ "$misses" -eq 0 ]; then
    next=$(busctl get-property org.freedesktop.systemd1 \
      /org/freedesktop/systemd1/unit/kubelab_2dedge_2dliveness_2etimer \
      org.freedesktop.systemd1.Timer NextElapseUSecMonotonic | awk '{ print $2 }')
    left=$(awk -v next_usec="${next:-0}" -v up="$(cut -d ' ' -f 1 "$uptime_file")" -v runs="$left" 'BEGIN {
      s = next_usec / 1000000 - up; first = s > 0 ? int((s + 59) / 60) : 0; print first + runs - 1 }')
  fi
  [ "$left" -ge 1 ] || left=1
  echo "$misses of $grace misses counted, and it fails on miss $grace: run the check again in about $left min"
}

watchdog_armed() {
  usec=$(systemctl show -p RuntimeWatchdogUSec --value)
  [ -n "$usec" ] && [ "$usec" != 0 ]
}

job_table() { systemctl list-jobs --no-legend --plain 2>/dev/null; }
queued_jobs() { job_table | awk '{ printf "%s%s", sep, $2; sep = " " }'; }

# `systemd-analyze time` fails until the boot finishes, so an unfinished boot names
# the jobs it still waits for instead (#2675). Any other failure says what it was.
if analyzed=$(systemd-analyze time 2>&1); then
  echo "INFO $(printf '%s\n' "$analyzed" | head -n 1)"
else
  case $analyzed in
    *"not yet finished"*)
      queued=$(queued_jobs)
      echo "INFO boot not finished, jobs still queued: ${queued:-none}"
      ;;
    *) echo "INFO startup time unavailable: $(printf '%s\n' "$analyzed" | head -n 1)" ;;
  esac
fi

# The boot finishes once systemd's job table first empties (lesson-653), so an
# unfinished one is judged by its jobs, not by the clock: timers that catch up a
# missed run after a random delay can join a boot that is still running, so a
# fixed time limit would be either too long or wrong. A service start job ends
# when its own TimeoutStartSec does, and `infinity`, a oneshot's default, means
# it never has to. Only running start jobs are judged; a waiting one has not
# started. `degraded` is a finished boot with failed units, judged below.
system_up() {
  case $(systemctl is-system-running 2>/dev/null) in running | degraded) return 0 ;; esac
  return 1
}
boot_finished() {
  system=$(systemctl is-system-running 2>/dev/null)
  case $system in
    running | degraded)
      pass "boot finished"
      return
      ;;
    starting | initializing) ;;
    *)
      fail "boot finished: the system is ${system:-unknown}"
      return
      ;;
  esac
  unbounded=
  bounded=
  for unit in $(job_table | awk '$2 ~ /\.service$/ && $3 == "start" && $4 == "running" { print $2 }'); do
    timeout=$(systemctl show -p TimeoutStartUSec --value "$unit")
    if [ "$timeout" = infinity ]; then
      unbounded="${unbounded:+$unbounded }$unit"
    else
      bounded="${bounded:+$bounded, }$unit ($timeout)"
    fi
  done
  # The table can empty between the two reads, so an empty one asks again.
  if [ -n "$unbounded" ]; then
    fail "boot finished: held by $unbounded, with no start timeout"
  elif [ -z "$bounded" ] && system_up; then
    pass "boot finished"
  else
    wait_for "boot finished: not yet, running ${bounded:-no service start job}: run the check again after the longest"
  fi
}
boot_finished
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
for container in coredns pihole; do
  check "container $container up" container_up "$container"
  check "container $container publishes its ports" ports_in_effect "$container"
done

if [ "$expect" = no-lan ]; then
  check "$lan present without a carrier, as this case expects" unplugged "$lan"
fi
check "LAN address on $lan" lan_address_set
check "route to $lan_cidr on $lan" lan_route
check "DNS answers on the LAN address" lan_dns

# The liveness check fails on a missing uplink, and the page its failure sends
# fails too: the edge has no route out. In that case both are expected, the page
# by the name systemd resolved from the unit's own OnFailure= line.
reporter=kubelab-edge-liveness.service
expected=
if [ "$expect" = no-uplink ]; then
  missing "uplink adapter $uplink" test -e "$sys_net/$uplink"
  if pages "$reporter"; then
    pass "$reporter failed on the missing uplink"
  elif eta=$(liveness_pending "$tries"); then
    wait_for "$reporter failed on the missing uplink: not yet, $eta"
  else
    fail "$reporter failed on the missing uplink"
  fi
  expected="$reporter $(systemctl show -p OnFailure --value "$reporter")"
else
  check "lease on $uplink" uplink_lease
  check "default route out $uplink" default_route
  check "kubelab-edge-shaper.service active" systemctl is-active --quiet kubelab-edge-shaper.service
  check "tailnet session running" tailnet_up
  check "subnet route $lan_cidr primary on the tailnet" advertises_lan
fi

# A run a timer started is a scheduled job, not something the boot brings back, and
# its own page reports its failure. An outage the case caused fails it too, along
# with that page: node-backup-ship cannot reach R2 without the uplink. A run whose
# page failed or does not exist reached nobody, so it is named apart. The edge's
# own timers run what it serves, so they are judged like everything else.
failed_now=" $(systemctl --failed --no-legend --plain | awk '{ printf "%s ", $1 }')"
paged=
unpaged=
for unit in $failed_now; do
  case $unit in kubelab-edge-*) continue ;; esac
  case " $(systemctl show -p TriggeredBy --value "$unit") " in
    *".timer "*)
      page=$(systemctl show -p OnFailure --value "$unit")
      expected="$expected $unit $page"
      case "$page:$failed_now" in
        :* | *" $page "*) unpaged="${unpaged:+$unpaged }$unit" ;;
        *) paged="${paged:+$paged }$unit" ;;
      esac
      ;;
  esac
done
[ -z "$paged" ] || echo "INFO failed scheduled runs, each paged: $paged"
[ -z "$unpaged" ] || echo "INFO failed scheduled runs nobody was paged for: $unpaged"

failed_units=$(systemctl --failed --no-legend --plain | awk -v expected="$expected" '
  BEGIN { n = split(expected, e, " "); for (i = 1; i <= n; i++) skip[e[i]] = 1 }
  !($1 in skip) { printf "%s%s", sep, $1; sep = " " }')
if [ -z "$failed_units" ]; then pass "no failed unit"; else fail "failed units: $failed_units"; fi

[ "$failed" -eq 1 ] || [ "$pending" -eq 0 ] || exit 2
exit "$failed"
