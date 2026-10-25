---
id: lesson-621-ufw-does-not-govern-forwarded-traffic
type: lesson
status: active
created: "2026-10-25"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, nftables, ufw, docker, tailscale]
---

# ufw sees only the forwarded traffic that Docker and Tailscale leave to it

**Context**: ADR-075 (NET-005) makes the RPi4 the lab edge on a shared hotel
uplink, and gives the `gateway` role an nftables table, `inet kubelab`, that
drops what arrives on the uplink. The first draft of its D3 said that traffic
had to pass both ufw and `inet kubelab`, so the two rule sets intersected and a
drop in either one was enough.

**Problem**: That holds for traffic delivered to the host. For traffic the host
forwards it holds only in part. ufw does not have a base chain of its own. Its rules
are chains jumped from iptables' `FORWARD` in the `filter` table, and that
chain is shared:

- Tailscale inserts `-j ts-forward` at position 1 when it starts
  (`util/linuxfw/iptables_runner.go`).
- Docker inserts `DOCKER-USER` and `DOCKER-FORWARD` at the top when its daemon
  starts (Docker's "Packet filtering and firewalls" page says published ports
  bypass ufw).
- ufw appends its jumps to the end of `FORWARD` when its chains do not exist
  yet, and a `ufw reload` empties its chains but leaves the jumps where they are
  (`/usr/lib/ufw/ufw-init-functions`, ufw 0.36.2).

Tailscale's and Docker's chains accept their own traffic, and an accept there
ends the packet's pass through `FORWARD`. What they do not accept falls through
to ufw's chains and its default forward policy: on the edge that includes the
LAN-to-uplink NAT, which is why the `gateway` role sets
`DEFAULT_FORWARD_POLICY="ACCEPT"`. So ufw governs part of the forward path, the
part nothing ahead of it accepted, and cannot restrict the rest. The order of
the jumps is insertion order, not a property of the chain. ufw starts before the network, so on a booted host Tailscale's and
Docker's jumps sit ahead of ufw's, and the traffic they accept never reaches
ufw's rules. That is the usual order, not a guaranteed one: nothing in the
ruleset enforces it. It also assumes ufw's default `MANAGE_BUILTINS=no` (with
`yes`, ufw flushes the built-in chains and its own jumps come first), Tailscale
in its default iptables mode, and a Docker recent enough to create
`DOCKER-FORWARD`. On the RPi4 the point was moot anyway: the baseline of 2026-10-25 read
`DEFAULT_FORWARD_POLICY="ACCEPT"`, and Pi-hole and CoreDNS publish on
`0.0.0.0`, the case #959 measured on other nodes. Under the draft's model, a
test that counted ufw's rules as part of the forward policy would have passed a
ruleset in which Docker forwards everything from the uplink.

**Solution**: The prior-art review found it before the tasks were frozen, not a
failure. D3 was rewritten: ufw governs what the host accepts, and `inet kubelab`
alone restricts what it forwards, so its forward drops are written to be
complete without ufw. A drop in any base chain is final, so those drops hold
whatever Docker's and Tailscale's chains accept.
`tests/test_gateway_firewall_render.py::test_nothing_new_is_forwarded_from_the_uplink`
renders the ruleset and checks the uplink-to-LAN, uplink-to-AP and
uplink-to-Docker-bridge drops, with nothing taken from ufw (#2666). DHCP is the
opposite case: requests are delivered to the host, so they pass both rule sets.
ufw's default-deny input had been dropping every one on `eth0` (27 in the first
five minutes after boot), and the role now allows udp 67 there.

**Rule**: On a host that runs Docker or Tailscale, do not use ufw to restrict
forwarded traffic: its forward rules never see what Docker's and Tailscale's
chains accept. Its forward policy still applies to the rest, so on a host that
forwards, such as the edge with its NAT, that policy stays ACCEPT: a DROP there
breaks the forwarding without restricting what Docker and Tailscale accept. A
forward restriction belongs in an nftables base chain of its own,
with drops that are complete without ufw, and a test of that policy must not
count ufw's rules. Before naming the firewall that governs a flow, ask whether
the flow is delivered to the host or forwarded through it. This makes `ufw route`
rules unreliable, not inert: do not delete them on this lesson's authority, and do
not count on them either.

**Tags**: `#nftables` `#ufw` `#docker` `#tailscale` `#net-005` `#pr-2666`
