#!/bin/sh
# Says whether the edge's uplink is up, behind a portal, or dead (NET-005 AC5,
# ADR-075 D3). `make edge-status` runs it over SSH; it needs no root.
#
# Usage: kubelab-edge-status <uplink interface>
#
# Exit codes:
#   0   up: the connectivity check answered 204 over the uplink
#   2   portal: it answered something else, which is a portal's redirect or page
#   3   dead: no adapter, no lease, no resolver, or no HTTP answer
#   4   unknown: the lease exists but this user cannot read it
#   64  usage
#
# The check goes out the uplink by name, so the tailnet or the LAN cannot answer for
# it, and never follows a redirect, since the redirect is what says "portal". Its host
# is resolved first through the public resolvers, then through the one the lease
# offers: before a login, many portals answer DNS only from their own resolver.
# Which of the two answers is reported too, because it decides how the login is done.
#
# The uplink's MAC is compared with the one the role pinned in the .link file, the
# one in SOPS that the portal's entitlement is bound to. Neither MAC is printed, and
# neither is any address: the output lands in terminals and in a spec's evidence.
set -u

usage() {
  echo "usage: $(basename "$0") <uplink interface>" >&2
  exit 64
}

[ $# -eq 1 ] || usage
uplink=$1
sys_net=${EDGE_SYS_NET:-/sys/class/net}
leases_dir=${EDGE_LEASES_DIR:-/run/systemd/netif/leases}
link_file=${EDGE_LINK_FILE:-/etc/systemd/network/10-kubelab-uplink.link}
resolv_conf=${EDGE_RESOLV_CONF:-/etc/resolv.conf}
check_host=connectivitycheck.gstatic.com

# Prints the value of a KEY=value line, or nothing when the file is unreadable.
field() {
  sed -n "s/^$1=//p" "$2" 2>/dev/null | head -n 1
}

# Prints the first IPv4 address a resolver gives for the check's host.
resolve() {
  dig +short +time=2 +tries=1 -b "$address" "@$1" "$check_host" A 2>/dev/null |
    grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -n 1
}

mac_report() {
  pinned=$(field PermanentMACAddress "$link_file" | tr 'A-F' 'a-f')
  current=$(cat "$sys_net/$uplink/address" 2>/dev/null | tr 'A-F' 'a-f')
  if [ -z "$pinned" ] || [ -z "$current" ]; then
    echo unreadable
  elif [ "$pinned" = "$current" ]; then
    echo "matches SOPS"
  else
    echo "differs from SOPS"
  fi
}

report() {
  echo "uplink: $1"
  echo "lease: $lease"
  echo "public resolver: $public_report"
  echo "lease resolver: $lease_report"
  echo "uplink MAC: $(mac_report)"
  exit "$2"
}

lease=no
public_report="not asked"
lease_report="not asked"
ifindex=$(cat "$sys_net/$uplink/ifindex" 2>/dev/null)
[ -n "$ifindex" ] || report "dead (no adapter named $uplink)" 3
lease_file=$leases_dir/$ifindex
# networkd writes its leases world-readable. One this user cannot read says nothing
# about the uplink, so it is not reported as a missing lease.
if { [ -d "$leases_dir" ] && ! [ -x "$leases_dir" ]; } ||
  { [ -e "$lease_file" ] && ! [ -r "$lease_file" ]; }; then
  lease=unreadable
  report "unknown (cannot read the lease as $(id -un))" 4
fi
address=$(field ADDRESS "$lease_file")
[ -n "$address" ] || report "dead (no DHCP lease)" 3
lease=yes

public_ip=
# shellcheck disable=SC2013 # one address per line, and a pipe would lose public_ip
for server in $(sed -n 's/^nameserver[[:space:]]*//p' "$resolv_conf" 2>/dev/null); do
  public_ip=$(resolve "$server")
  [ -n "$public_ip" ] && break
done
public_report=${public_ip:+answers}
public_report=${public_report:-no answer}

lease_ip=
lease_dns=$(field DNS "$lease_file" | cut -d ' ' -f 1)
if [ -z "$lease_dns" ]; then
  lease_report="none offered"
else
  lease_ip=$(resolve "$lease_dns")
  lease_report=${lease_ip:+answers}
  lease_report=${lease_report:-no answer}
fi

ip=${public_ip:-$lease_ip}
[ -n "$ip" ] || report "dead (no resolver answers)" 3

code=$(curl --interface "$uplink" --silent --output /dev/null --max-time 5 \
  --write-out '%{http_code}' --resolve "$check_host:80:$ip" \
  "http://$check_host/generate_204" 2>/dev/null)
case $code in
  204) report up 0 ;;
  '' | 000) report "dead (no HTTP answer)" 3 ;;
  *) report "portal (HTTP $code instead of 204)" 2 ;;
esac
