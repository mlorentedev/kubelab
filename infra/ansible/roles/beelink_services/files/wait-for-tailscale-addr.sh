#!/bin/sh
# Block until <address> is assigned to tailscale0, then exit 0. Fail loudly if it
# never appears.
#
# Why this exists: Docker publishes these containers on the node's Tailscale
# address rather than 0.0.0.0, because a published port is governed by its bind
# address and nothing else — Docker's DNAT runs before ufw's filter chains, so an
# interface-scoped firewall rule on a published port is decoration.
#
# The cost of that correct choice is a boot ordering race. Docker starts before
# tailscaled has finished assigning the address, the bind fails with
# `cannot assign requested address`, and the container exits. Docker's restart
# policy does NOT retry it, because the failure is in container *start*, not a
# process that exited — measured on 2026-08-14: RestartCount=0 with
# `restart: unless-stopped` set.
#
# Waiting on tailscaled.service is not enough: the unit being active does not
# mean the address is on the interface yet. This waits for the address itself.

set -eu

addr=${1:?usage: wait-for-tailscale-addr <ipv4>}
iface=${2:-tailscale0}
attempts=${3:-60}
delay=2

i=0
while [ "$i" -lt "$attempts" ]; do
    if ip -4 addr show "$iface" 2>/dev/null | grep -qw "$addr"; then
        echo "$addr is up on $iface after $((i * delay))s"
        exit 0
    fi
    i=$((i + 1))
    sleep "$delay"
done

# Deliberately an error, not a silent give-up: a unit left hanging is invisible,
# whereas a failed one shows up in `systemctl --failed`.
echo "timed out after $((attempts * delay))s waiting for $addr on $iface" >&2
exit 1
