---
tags: [spec, verification, templates]
created: "2026-10-25"
---

# Verification - NET-005-lab-edge-site-modes

## Baseline (2026-10-25, before any change)

Read-only capture over the homelab LAN (`ssh` to `lan_ip`, host key checked against the pinned tailnet entry with `HostKeyAlias`). The PSK was never read into the transcript: only its length and character classes were computed on the host. Site SSIDs are omitted here on purpose (see the proposal's risk on site-identifying data).

- **System:** Ubuntu 24.04.4, kernel `6.8.0-1065-raspi`. `iw` is not installed.
- **Network config:** one hand-written netplan file from 2026-03-15, renderer networkd. `eth0` is static on `lan_ip`; `enx<MAC>` (the USB Ethernet adapter, whose name embeds its MAC) is DHCP with metric 100; `wlan0` is a DHCP client of the home SSID with metric 600 and `regulatory-domain: US` (the bootstrap runbook says `ES`). cloud-init's network config is disabled.
- **The home PSK:** checked on the host for length and character classes. The result is not recorded in this public file, since it would narrow an offline search; the operator has it.
- **Resolver:** a static `/etc/resolv.conf` (8.8.8.8, 1.1.1.1), with systemd-resolved masked.
- **Sysctls:** `ip_forward=1`, `rp_filter=2` (loose), `arp_ignore=0`, `arp_announce=0`, and IPv6 enabled.
- **ufw:** default deny incoming, allow routed (`DEFAULT_FORWARD_POLICY="ACCEPT"`). 22, 80, 443 and 41641 are allowed from anywhere, over IPv4 and IPv6. `udp dport 67` jumps to the input policy, which drops it: 27 packets in the first five minutes after boot.
- **DHCP:** dnsmasq listens on `0.0.0.0%eth0:67` and its journal is empty. The operator's laptop on the switch got no lease (NetworkManager timed out) and reached the RPi4 only with a static address outside the pool.
- **Published ports:** Pi-hole on `0.0.0.0:53` (tcp and udp) and `0.0.0.0:80`; CoreDNS on `0.0.0.0:5353` (tcp and udp) and its health endpoint on `lan_ip:8080`. sshd listens on `0.0.0.0:22` and `[::]:22` through socket activation, although `sshd_config` says `ListenAddress 0.0.0.0`.
- **nftables:** the gateway's `inet kubelab` table holds only a postrouting masquerade.
- **Docker bridges** are allocated from `172.80.0.0/12`, a public range (#2136): `172.80.0.0/24` to `172.80.3.0/24`, plus `172.17` and `172.18`.
- **Tailscale:** logged out and unable to resolve `vpn.kubelab.live` with no uplink. The prefs still hold `AdvertiseRoutes: [172.16.1.0/24]` and `RouteAll: false`.
- **USB:** nothing but the internal hub; both adapters were on the operator's laptop at capture time.

## Prior art reviewed (2026-10-25, before tasks were frozen)

Three web reviews looked at how others built a portable lab edge, hardened a router on a shared uplink, and detected portal expiry. What changed the plan, with its source:

- **ufw is not the forward policy.** Tailscale's `ts-forward` and Docker's chains accept forwarded traffic before ufw's rules, so only `inet kubelab` restricts it (Docker's packet-filtering docs; Tailscale `iptables_runner.go`). ADR-075 D3 had claimed an intersection of ufw and nftables, which is false for forwarded traffic.
- **A missing series resolves.** Grafana routes an instance whose series disappears as `MissingSeries`, resolved, so a per-target probe must log every target with its result as a value (Grafana alerting docs). This changed AC12.
- **The radio may offload WPA2 to its firmware**, which holds one key, so hostapd's multi-PSK overlap is unproven on brcmfmac (a Raspberry Pi forum report and hostapd's `beacon.c`; unverified on this firmware). This gates AC10, which now has a fallback.
- **Pre-login DNS and portals.** Travelmate's and GL.iNet's documentation and Tailscale's captive-portal docs agree that custom DNS, ad-blocking and VPNs are what break a portal login. The earlier measurement used the site's own resolver, so it is now a gate before the login (AC5).
- **The AP radio's firmware halts** under a weak client or an eighth station (raspberrypi/firmware#1403). This is why D5 adds the watchdog and the liveness ladder (AC13).
- **Shaping both directions.** The OpenWrt SQM documentation and `tc-cake(8)` both shape ingress through IFB with `nat dual-dsthost`. Shaping egress only does not reach the download queue (AC8).
- **`rp_filter`.** Tailscale supports strict filtering on subnet routers from 1.96.2 (tailscale/tailscale#18860). The RPi4 runs 1.102.4, read on 2026-10-25.

Considered and not adopted:

- **Swapping the radios.** The OpenWrt Travelmate build uses the built-in radio as the uplink. The decision triggers in ADR-075 D2 stand, and smos/nomad-hotspot reports the same split as ours working reliably.
- **A second uplink with failover (mwan3).** It is out of scope here.
- **BSSID pinning.** It breaks hotels with several access points, and a cloned BSSID defeats it.
- **DHCP option 114 as a portal signal.** An attacker on the uplink can inject it, and no hotel deployment of RFC 8908 was found.

Read on the RPi4 the same day:

- `rtw88_8822bu` ships in the 6.8 raspi kernel.
- Cypress's minimal firmware is installed (`cyfmac43455-sdio-minimal.bin.zst`), so the station-cap fallback swaps a symlink and needs no download.
- `/dev/watchdog` exists, unused.
- `vcgencmd get_throttled` reads `0x0`.

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

### Task 11: PR 3 live over the LAN (AC4), 2026-10-25

`make provision NODE=rpi4 ENV=prod BOOTSTRAP=1 TAGS=gateway`, run from the PR 3 branch with no PR 4 content on it, twice in a row:

- run 1: `ok=29 changed=6 failed=0`; run 2: `ok=26 changed=0 failed=0`.
- `nft list tables` shows `inet kubelab` beside iptables-nft's own tables, which the scoped stop leaves alone. `nftables.service` stops with `nft delete table inet kubelab`, and the input chain opens with `iifname "uplink0" ct state established,related accept`.
- `rp_filter` reads `all=0`, and `default`, `eth0`, `wlan0` and `tailscale0` read `2`. The uplink's `1` lands when `uplink0` exists (PR 4).
- A host on the switch takes a lease from the RPi4. bee ran `busybox udhcpc -i enp1s0 -n -q -f -R -s /bin/true`, which completes the exchange without configuring the interface and releases on exit. dnsmasq logged `DHCPDISCOVER(eth0)`, `DHCPOFFER(eth0) 172.16.1.3`, `DHCPREQUEST(eth0)` and `DHCPACK(eth0) 172.16.1.3 kubelab-bee`, the reservation from `networking.nodes.beelink`.

The RPi4's journal reads 2026-10-23 for these lines: with no uplink it has no NTP, and its clock drifts until PR 4 gives it one.

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **Hand changes to undo (AC11), 2026-10-25.** To reach the RPi4 over the switch with no DHCP, the operator's laptop got these NetworkManager changes by hand:
  - a new profile `lab-bootstrap` on the USB Ethernet adapter, with a static address outside the DHCP pool, `never-default`, `ignore-auto-dns`, IPv6 disabled and `autoconnect no`;
  - on "Wired connection 1": `ipv4.never-default yes`, `ipv4.ignore-auto-dns yes`, `ipv6.method disabled`.

  Both are replaced by the AC11 target and removed once it exists.
-

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/NET-005-lab-edge-site-modes/` -> `specs/archive/NET-005-lab-edge-site-modes/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
