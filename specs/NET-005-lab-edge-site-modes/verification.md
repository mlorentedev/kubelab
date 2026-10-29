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
- A host on the switch takes a lease from the RPi4. bee ran `busybox udhcpc -i enp1s0 -n -q -f -R -s /bin/true`, which completes the exchange without configuring the interface and releases on exit. dnsmasq logged `DHCPDISCOVER(eth0)`, `DHCPOFFER(eth0) 172.16.1.3`, `DHCPREQUEST(eth0)` and `DHCPACK(eth0) 172.16.1.3 kubelab-bee`, the reservation from `networking.nodes.beelink`. The exchange is complete but nothing was configured with it: it shows the server answering, which the baseline lacked. The laptop was not on the switch for this run.

The RPi4's journal reads 2026-10-23 for these lines: with no uplink it has no NTP, and its clock drifts until PR 4 gives it one.

### B1-EVIDENCE: the uplink adapter on the RPi4, 2026-10-26

The operator moved the adapter to a USB 2.0 port on an extension cable. The RPi4 enumerated it with the `rtw_8822bu` driver, and its address is the permanent one (`addr_assign_type` 0), so the MAC the portal authorizes is read from the RPi4 itself.

### Bring-up progress, 2026-10-28

Partial results, kept apart from the `### B<n>-EVIDENCE` headings on purpose: `features.json` reads such a heading as the step's proof, so a step gets one only when its whole criterion is observed.

- **B2.** The full play with `BOOTSTRAP=1` over the LAN finished `ok=182 changed=6 failed=0`. For the boot that began 2026-10-27T00:52Z (`/proc/stat` btime), systemd's monotonic timestamps put `inet kubelab` active at 9.6 s and systemd-networkd's start at 15.5 s; the journal could not say, because its size cap had dropped the boot's first seconds (lesson-641). Left: `networkctl renew uplink0` with the drops loaded, and the renewed lease in the journal.
- **B3.** Not recorded. The portal login (B4) came first, so at this site the reading can no longer precede it. Left: the gate's result, and with it task 31's decision.
- **B4.** The portal login went through `make edge-lan-link ROUTE=1` with the laptop's own Wi-Fi off. The form left through the adapter, and `make edge-status` then read `uplink: up`. Left: the uplink's MAC read unchanged after a reboot and after a re-provision, and undoing the hand changes (the `lab-bootstrap` profile, "Wired connection 1").
- **B5.** The AP is provisioned and serving: the 2026-10-28 boot check reads hostapd active, the DHCP server listening and the lab Wi-Fi on `wlan0`. Left: saved devices rejoining, rpi3 on its reservation and Kuma's route answering, each observed.
- **B6.** Both nodes' Tailscale prefs were compared read-only with their plays (lesson-629). rpi4 matched. rpi3 accepted routes its play declares off, which the role's `tailscale set` convergence then corrected (#2685). The 2026-10-28 boot check reads the subnet route primary on the tailnet. Left: `make headscale-rejoin` for both nodes, rpi3's `TAGS=tailscale` second run at `changed=0`, and the Headscale expiry read.
- **B11.** ace1, bee and ace2 each had a default route through the RPi4 and a 204 from the connectivity probe (2026-10-27). Left: a `DHCPACK(eth0)` at this step (the one on record is task 11's, from before the uplink existed) and `make test-e2e ENV=staging`.
- **B12.** The second provision (2026-10-28) reported `ok=182 changed=1 failed=0`. The one change is apt's cache refresh (`cache_valid_time: 3600`), which fires on time elapsed, not on drift. Left: a run that reports `changed=0` as written, and the 48-hour soak's rtw88 check.
- **B14.** A baseline first: `make edge-boot-check VIA=tailnet` passed 22 of 22 checks on 2026-10-28 with everything plugged in, on the boot that began 2026-10-27T00:52Z. Then the cases, each checked 10 minutes after power returned (times UTC, 2026-10-29):
  - **T1 warm reboot**, 01:17: 22 of 22, startup 57.4 s, ruleset at 9.5 s and networkd at 15.5 s. `make reboot` could not reach the edge from the LAN (its inventory is the tailnet one), which `BOOTSTRAP=1` now does.
  - **T2 power cut**, 01:28: 22 of 22, startup 59.4 s.
  - **T3 no uplink adapter**, 01:40: exit 2. The shaper had failed with result `dependency` and its page with it (#2766), and so had a timer's `node-backup-ship` run with its page, which a boot does not own. The startup line was empty, because the boot had not finished.
  - **T3, adapter plugged back**, 01:47: the adapter came back as `uplink0` but nothing started its supplicant: no lease, no route, no tailnet session, no subnet route (#2766).
  - **T2 again, restored**, 02:00: 22 of 22, startup 56.9 s, with the adapter in the other USB port.
  Left: T4, then T3 again with #2766 deployed, its replug bringing the lease, the route and the tailnet back within 2 minutes.
- **B7, B8, B9, B10, B13.** Not started.

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
- **The uplink is checked, never rebooted for (AC13), 2026-10-25.** Task 28 has the liveness check the uplink's lease, and AC13 recovers the edge "where a reboot can". A present adapter with no lease is the site (down, out of range, a changed passphrase), which a reboot cannot fix, and the reboot would cost rpi3 its Wi-Fi and the homelab its route. So the check reports it after the grace and does nothing else. An adapter that disappeared gets its driver reloaded once per incident; an unplugged one looks the same, so the edge does no more.
- **The AP's `operstate` under hostapd (AC13), pending B10.** The check reads `up`, as task 28 words it; brcmfmac turns the carrier on when it starts the BSS. B10 reads it on the edge with the AP serving. A driver that reported anything else would escalate on a healthy AP: one driver reload, one reboot, another reload, then the latch holds and pages. B10 also shows whether the unload succeeds on the serving edge: `brcmfmac_wcc` holding `brcmfmac` was read with `wlan0` down and no hostapd, and the ladder stops hostapd before the unload.
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
