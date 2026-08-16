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
# tailscaled has finished assigning the address, and the bind fails.
#
# That race has TWO outcomes, and the second is the dangerous one:
#
#   1. The container exits. Docker's restart policy does NOT retry it, because
#      the failure is in container *start*, not a process that exited — measured
#      2026-08-14: RestartCount=0 with `restart: unless-stopped` set.
#   2. The container starts WITHOUT the port published, and keeps running.
#      Measured 2026-08-15 on beelink and ace1: HostConfig.PortBindings asks for
#      100.64.0.3:61208 while NetworkSettings.Ports is `{}`. `docker ps` reports
#      it Up with no ports, nothing listens, and `docker compose up -d` will
#      never fix it because the compose spec hash is unchanged.
#
# The second is worse precisely because it looks healthy. A crashed container is
# visible; one that has been Up for days serving nothing is not. It left five of
# seven Glances endpoints silently unreachable from the dashboard that scrapes
# them.
#
# Shared between roles deliberately: this lives in playbooks/files/ rather than
# in one role, because every role that publishes on a Tailscale address needs it
# and a second copy would drift.
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
