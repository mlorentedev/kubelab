#!/bin/sh
# Reports an uplink DHCP lease that lands inside a network the lab owns (NET-005
# AC7, ADR-075 D3). kubelab-edge-lease-check.path runs it whenever networkd writes
# or removes a lease, and a non-zero exit pages through OnFailure=.
#
# Usage: kubelab-edge-lease-check <interface> <name>=<cidr>...
#
# Exit codes:
#   0   no collision, or no lease to check
#   1   the address, a gateway or an offered route lands inside a named network
#   2   the lease cannot be read: the check is blind, so it pages as well
#   64  usage
#
# A route counts when it overlaps a network in either direction: one that contains
# a network (a /1, or 172.16.0.0/12) is the TunnelVision shape. The default route
# does not count, since option 121 carries it routinely. The site's prefix is not
# checked: a site whose subnet contains the homelab LAN is NET-006's to fix
# (#2662), and paging on every renewal until then would bury the real cases.
#
# networkd's lease file calls itself private. It is still the only place that
# shows the routes a site offered, because the uplink refuses them (netplan's
# use-routes: false), and `netplan ip leases` reads the same file. The format is
# systemd 255's dhcp_lease_save(): ADDRESS=, ROUTER= (space-separated), and
# CLASSLESS_ROUTES= or STATIC_ROUTES= as space-separated `dst/len,gw`. A lease with
# no readable address exits 2, so a format change pages instead of passing.
#
# Every value in the lease comes from the site's DHCP server, and this output
# becomes the page body (kubelab-notify quotes the unit's journal). The check only
# repeats values that parsed as addresses, and names anything else by its key.
set -eu

usage() {
  echo "usage: $(basename "$0") <interface> <name>=<cidr>..." >&2
  exit 64
}

[ $# -ge 2 ] || usage
iface=$1
shift
# The name becomes a path under sysfs.
case $iface in
  '' | . | .. | -* | *[!A-Za-z0-9_.-]*)
    echo "refusing an implausible interface name" >&2
    exit 64
    ;;
esac

leases_dir=${EDGE_LEASES_DIR:-/run/systemd/netif/leases}
sys_net=${EDGE_SYS_NET:-/sys/class/net}

lease=/dev/null
state=present
if [ ! -r "$sys_net/$iface/ifindex" ]; then
  state="absent: $iface is not present"
else
  ifindex=$(cat "$sys_net/$iface/ifindex")
  case $ifindex in
    '' | *[!0-9]*)
      echo "$iface: cannot read its ifindex, so this check is blind" >&2
      exit 2
      ;;
  esac
  if [ -e "$leases_dir/$ifindex" ]; then
    lease=$leases_dir/$ifindex
  else
    state="absent: $iface holds no lease"
  fi
fi

exec awk -v iface="$iface" -v nets="$*" -v state="$state" '
function ip4(s,    part, n, i) {
  n = split(s, part, ".")
  if (n != 4) return -1
  for (i = 1; i <= 4; i++)
    if (part[i] !~ /^[0-9]+$/ || length(part[i]) > 3 || part[i] + 0 > 255) return -1
  return ((part[1] * 256 + part[2]) * 256 + part[3]) * 256 + part[4]
}

function plen(s) {
  if (s !~ /^[0-9]+$/ || length(s) > 2 || s + 0 > 32) return -1
  return s + 0
}

# Whether two addresses share their first len bits. No bitwise operators and no
# `^`: POSIX awk has neither the first, and busybox can be built without the second.
function same_block(a, b, len,    size, k) {
  size = 1
  for (k = len; k < 32; k++) size *= 2
  return int(a / size) == int(b / size)
}

function blind(key) {
  printf "%s: cannot read %s in the lease, so this check is blind\n", iface, key
  blinded = 1
}

function check_address(kind, s, key,    n, i) {
  n = ip4(s)
  if (n < 0) { blind(key); return }
  for (i = 1; i <= count; i++)
    if (same_block(n, net_ip[i], net_len[i])) {
      printf "%s: lease %s %s is inside %s %s\n", iface, kind, s, net_name[i], net_cidr[i]
      collided = 1
    }
}

function check_route(s, key,    hop, dst, d, len, i, m) {
  if (split(s, hop, ",") != 2 || split(hop[1], dst, "/") != 2) { blind(key); return }
  d = ip4(dst[1]); len = plen(dst[2])
  if (d < 0 || len < 0 || ip4(hop[2]) < 0) { blind(key); return }
  if (len == 0) return
  for (i = 1; i <= count; i++) {
    m = len < net_len[i] ? len : net_len[i]
    if (same_block(d, net_ip[i], m)) {
      printf "%s: lease route %s/%d overlaps %s %s\n", iface, dst[1], len, net_name[i], net_cidr[i]
      collided = 1
    }
  }
}

BEGIN {
  count = split(nets, spec, " ")
  if (count == 0) { usage = 1 }
  for (i = 1; i <= count && !usage; i++) {
    eq = index(spec[i], "=")
    name = substr(spec[i], 1, eq - 1); cidr = substr(spec[i], eq + 1)
    if (eq < 2 || name !~ /^[a-z][a-z0-9_-]*$/ || split(cidr, c, "/") != 2) { usage = 1; break }
    net_name[i] = name; net_cidr[i] = cidr
    net_ip[i] = ip4(c[1]); net_len[i] = plen(c[2])
    if (net_ip[i] < 0 || net_len[i] < 0) usage = 1
  }
  if (usage) {
    print "networks are <name>=<a.b.c.d/len>, one or more" > "/dev/stderr"
    exit 64
  }
  if (state != "present") {
    sub(/^absent: /, "", state)
    printf "%s: nothing to check\n", state
    exit 0
  }
}

/^#/ { next }

{
  eq = index($0, "=")
  if (eq == 0) next
  key = substr($0, 1, eq - 1); value = substr($0, eq + 1)
  if (key == "ADDRESS") {
    seen_address = 1
    check_address("address", value, key)
  } else if (key == "ROUTER") {
    n = split(value, list, " ")
    if (n == 0) blind(key)
    for (j = 1; j <= n; j++) check_address("gateway", list[j], key)
  } else if (key == "CLASSLESS_ROUTES" || key == "STATIC_ROUTES") {
    n = split(value, list, " ")
    if (n == 0) blind(key)
    for (j = 1; j <= n; j++) check_route(list[j], key)
  }
}

END {
  if (usage) exit 64
  if (state != "present") exit 0
  if (!seen_address) blind("ADDRESS")
  if (blinded) exit 2
  if (collided) exit 1
  printf "%s: the lease is clear of every internal network\n", iface
}
' "$lease"
