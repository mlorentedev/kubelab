---
id: lesson-648-a-static-address-on-a-link-without-a-carrier-is-not-configured
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, netplan, systemd, docker, rpi4]
---

# A static address on a link without a carrier is not configured

**Context**: The lab edge's LAN address is static in netplan, on `eth0`. The coredns role bound CoreDNS's health port to that address, on the premise that a physical interface is configured before Docker starts. T4 of the NET-005 hard-reset test (#2661) boots the edge with the switch cable out.

**Problem**: The premise holds only with a cable. networkd's default is `ConfigureWithoutCarrier=no`, so with no carrier `eth0` stayed `no-carrier (configuring)` and had no address. Three things followed (#2732):

- CoreDNS exited on `cannot assign requested address` for its health port. A failed bind takes the container's whole port publication with it, `5353:53` included, so Pi-hole lost its upstream and went unhealthy. The same mechanism took staging DNS down on 2026-08-22, with the Tailscale address.
- netplan 1.1.2 renders `systemd-networkd-wait-online` with `-i <iface>:degraded` for each interface that is not `optional`. `eth0` was the only one, so wait-online failed after two minutes and the boot took 2 min 50 s.
- With no address there was no connected route for the LAN. `ip route get` for a LAN host answered `dev uplink0`, so tailnet traffic for the advertised subnet left through the uplink.

`ignore-carrier: true` alone does not fix the wait. netplan keeps `-i eth0:degraded` for an interface with a static address whatever `ignore_carrier` says, and `no-carrier` is below `degraded`.

**Solution**: Three changes, each closing one effect.

- `eth0` takes `ignore-carrier: true`. netplan writes `ConfigureWithoutCarrier=yes`, so the address and its connected route stay without a cable. LAN traffic then dies at `eth0` instead of leaving by the default route.
- `eth0` takes `optional: true`. No interface is left for netplan to wait for, so it does not pull wait-online in: its drop-in carries `ConditionPathIsSymbolicLink=` on a link the generator only creates for a non-optional interface.
- CoreDNS's health port binds `127.0.0.1`. Making `eth0` optional removed the ordering that had kept the LAN bind safe, and loopback exists before Docker starts.

`tests/test_gateway_uplink_render.py` holds both netplan keys and asks netplan which networkd key it writes. `tests/test_coredns_port_binds.py` fails on any bound port of the DNS stack that is not loopback. The live proof is T4 passing after a provision.

**Rule**: A container port bound to a node address depends on that address existing when Docker starts. A static address meets that only with a carrier, and a Tailscale address only after tailscaled. Publish bare or on loopback. A boot wait follows from which interfaces are not optional, so an interface the host can run without is `optional`.

**Tags**: `#net-017` `#net-005` `#netplan` `#docker` `#pr-TBD`
