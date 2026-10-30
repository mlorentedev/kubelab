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
- **B4.** The portal login went through `make edge-lan-link ROUTE=1` with the laptop's own Wi-Fi off. The form left through the adapter, and `make edge-status` then read `uplink: up`. Completed 2026-10-30, see `### B4-EVIDENCE` below.
- **B5.** The AP is provisioned and serving: the 2026-10-28 boot check reads hostapd active, the DHCP server listening and the lab Wi-Fi on `wlan0`. On 2026-10-30 dnsmasq's leases held rpi3 on its reservation (`10.0.0.157`, `b8:27:eb:3d:8e:54`) and saved devices back on the lab Wi-Fi (a phone, a tablet, a watch). Left: Kuma's route answering, observed.
- **B6.** Both nodes' Tailscale prefs were compared read-only with their plays (lesson-629). rpi4 matched. rpi3 accepted routes its play declares off, which the role's `tailscale set` convergence then corrected (#2685). The 2026-10-28 boot check reads the subnet route primary on the tailnet. On 2026-10-30 `make headscale-rejoin NODE=rpi4` was a no-op over the LAN (`ok=23 changed=0`, no key minted), and rpi3's full provision at c737c74e, which carries the `tailscale` role, read `changed=0` on its second run. `NODE=rpi3` from the switch could not reach rpi3 (`10.0.0.157`, timed out before any task ran): it runs over the lab Wi-Fi address, so the controller has to be on the lab Wi-Fi (`docs/runbooks/lab-edge.md`). On 2026-10-30, with the controller on the lab Wi-Fi, `make headscale-rejoin NODE=rpi3` reached rpi3 through the bootstrap inventory and was a no-op (`ok=23 changed=0`, no key minted). Left: the Headscale expiry read, if either node rejoins for real.
- **B11.** Completed 2026-10-30, see `### B11-EVIDENCE` below.
- **B12.** The second provision (2026-10-28) reported `ok=182 changed=1 failed=0`. The one change is apt's cache refresh (`cache_valid_time: 3600`), which fires on time elapsed, not on drift. On 2026-10-29 the edge's provision at 973113b9 read `changed=0`, the configuration B14 ran on. Left: the 48-hour soak's rtw88 check. The journal holds only about 8 hours (19.7M against `SystemMaxUse=20M`, #2702), but rsyslog keeps every kernel line in `kern.log` for weeks, and `make edge-soak` (#2811) reads the soak from there. The boot that began 2026-10-29T21:50Z is the soak. At 4.5 h it read 0 resets and logged `firmware failed to leave lps state` twice in its first 3 hours, with no disconnect, lease change or liveness action in either minute, power save `on` and `disable_lps_deep` `N`. The operator chose to observe through the soak rather than change the role, which would restart it. #2807 tracks the LPS decision at the end of the soak.
- **B14.** Done. Every case passed after B12's `changed=0` provision, and again on #2797's configuration once T3 had found #2794. The first check after T4's cable went back in could not tell a cable from none (#2800). Redone over the LAN with #2800's carrier line, it reads `eth0 has a carrier`, 28 of 28 `OK`. See `### B14-EVIDENCE` below.
- **B7, B8, B9, B10, B13.** Not started.

### Hard-reset runs, 2026-10-29

Partial for B14, so kept apart from the `### B<n>-EVIDENCE` headings: T1 and T2 ran before the fixes below, and B14 runs after B12.

Each case was checked with `make edge-boot-check` 10 minutes after power returned. Times are UTC on 2026-10-29, read on the operator's machine, because the edge's own clock has no RTC and is not synced while its uplink is down.

- **T1 warm reboot**, 01:17: 22 of 22, startup 57.4 s, ruleset at 9.5 s and networkd at 15.5 s.
- **T2 power cut**, 01:28: 22 of 22, startup 59.4 s. The ruleset and networkd times were not read.
- **T3 and T4, first runs**, 01:40 to 02:00: they found #2766 (the replugged uplink never started its supplicant) and #2732 (the LAN address needed a carrier). Fixed by #2768, #2769, #2770 and #2771, and provisioned with `make provision NODE=rpi4 ENV=prod BOOTSTRAP=1`: `ok=192 changed=13 failed=0`. The baseline after it, at 05:17, passed 25 of 25.
- **T3 no uplink adapter**, 05:28: every check `OK`, the adapter missing and `kubelab-edge-liveness.service` failed on it, as the case expects. Ruleset at 9.7 s, networkd at 15.5 s. Two earlier checks of the same boot ran inside the liveness grace and read FAIL (#2774). The boot had not finished, with tailnet-bound units still queued (#2776).
- **T3, adapter plugged back**: the first replug started nothing. `udevadm monitor` showed why: the add event that renames the adapter carries `ID_RENAMING=1`, and the move event that activates it carried no `SYSTEMD_WANTS` (lesson-650). Fixed by #2773 and provisioned with `TAGS=gateway`: `ok=90 changed=3 failed=0`. On the replug at 06:28, the move event carried `SYSTEMD_WANTS`, the supplicant started in the same second as the rename, and the check 2 minutes later passed every check, lease, default route, shaper, tailnet session and subnet route included (#2766, closed).
- **T4 no switch cable**, 07:11, through the tailnet: 26 of 26. `eth0` was present without a carrier, and its address, its route and DNS on the LAN address all held (#2732). Startup 52.1 s, ruleset at 10.7 s and networkd at 16.9 s. The shaper came up at boot through #2773's rule.
- **Cable plugged back**, 07:12: 25 of 25. The check has no line for `eth0`'s carrier, and since #2769 the LAN address, route and DNS hold without one, so this does not show the cable was back (#2800).

T1 and T2 ran on the configuration from before #2768 to #2773. T4 is a power cut on the current configuration with everything plugged in but the switch cable, so it also covers T2's path on that configuration. Every boot whose order was read (T1, T3, T4) loaded the ruleset before systemd-networkd started.

### B14-EVIDENCE: the hard-reset test, 2026-10-29

Run after B12's `changed=0` provision of the edge, at 973113b9. Each case was checked with `make edge-boot-check` once the boot had finished and, for T3, after the liveness grace. Boot times are the edge's clock, which NTP had synced for T1 and T2 (CET, UTC+1); the later boots ran on it unsynced.

T1 and T2 passed. T3 passed every check, but its boot waited 90 s for the missing adapter: #2794, fixed by #2797, which bounds that wait to 10 s and makes the check fail on systemd's default. As this section's B14 line required once a change touched the `gateway` role, T1, T3 and T4 then ran again on #2797's configuration and passed; T4 is a power cut, so it also covers T2's path there. Every boot loaded the ruleset before systemd-networkd started.

#### T1 warm reboot, 2026-10-29 (boot 17:08:28 CET; edge provisioned at 973113b9, idempotent run changed=0 just before)

```text
INFO Startup finished in 6.866s (kernel) + 30.030s (userspace) = 36.897s
OK   boot finished
INFO ruleset loaded at 9.3s, systemd-networkd started at 12.2s
OK   ruleset inet kubelab loaded
OK   ruleset loaded before systemd-networkd started
OK   hardware watchdog armed
OK   hostapd.service active
OK   dnsmasq.service active
OK   docker.service active
OK   tailscaled.service active
OK   kubelab-edge-liveness.timer active
OK   kubelab-edge-lease-check.timer active
OK   kubelab-edge-lease-check.path active
OK   DHCP server listening
OK   wlan0 serves the lab Wi-Fi
OK   container coredns up
OK   container coredns publishes its ports
OK   container pihole up
OK   container pihole publishes its ports
OK   LAN address on eth0
OK   route to 172.16.1.0/24 on eth0
OK   DNS answers on the LAN address
OK   lease on uplink0
OK   default route out uplink0
OK   kubelab-edge-shaper.service active
OK   tailnet session running
OK   subnet route 172.16.1.0/24 primary on the tailnet
OK   no failed unit
```

After the boot: `/etc/hosts` still carries the `KUBELAB DNS RESILIENCE` block and `cloud-init status` reads `disabled` (#2777).

#### T2 power cut, 2026-10-29 (boot 17:20:19 CET, `journalctl --list-boots` shows the new boot)

```text
INFO Startup finished in 7.380s (kernel) + 30.337s (userspace) = 37.717s
OK   boot finished
INFO ruleset loaded at 10.0s, systemd-networkd started at 13.1s
OK   ruleset inet kubelab loaded
OK   ruleset loaded before systemd-networkd started
OK   hardware watchdog armed
OK   hostapd.service active
OK   dnsmasq.service active
OK   docker.service active
OK   tailscaled.service active
OK   kubelab-edge-liveness.timer active
OK   kubelab-edge-lease-check.timer active
OK   kubelab-edge-lease-check.path active
OK   DHCP server listening
OK   wlan0 serves the lab Wi-Fi
OK   container coredns up
OK   container coredns publishes its ports
OK   container pihole up
OK   container pihole publishes its ports
OK   LAN address on eth0
OK   route to 172.16.1.0/24 on eth0
OK   DNS answers on the LAN address
OK   lease on uplink0
OK   default route out uplink0
OK   kubelab-edge-shaper.service active
OK   tailnet session running
OK   subnet route 172.16.1.0/24 primary on the tailnet
OK   no failed unit
```

The `KUBELAB DNS RESILIENCE` block survived the power cut too. `systemd-timesyncd` synchronized 24.5 s after boot (ntp.ubuntu.com).

#### T3 no uplink adapter, 2026-10-29 (boot 17:32:01 CET, dongle unplugged before the power cut)

```text
INFO Startup finished in 7.789s (kernel) + 2min 47.238s (userspace) = 2min 55.027s
OK   boot finished
INFO ruleset loaded at 10.4s, systemd-networkd started at 13.4s
OK   ruleset inet kubelab loaded
OK   ruleset loaded before systemd-networkd started
OK   hardware watchdog armed
OK   hostapd.service active
OK   dnsmasq.service active
OK   docker.service active
OK   tailscaled.service active
OK   kubelab-edge-liveness.timer active
OK   kubelab-edge-lease-check.timer active
OK   kubelab-edge-lease-check.path active
OK   DHCP server listening
OK   wlan0 serves the lab Wi-Fi
OK   container coredns up
OK   container coredns publishes its ports
OK   container pihole up
OK   container pihole publishes its ports
OK   LAN address on eth0
OK   route to 172.16.1.0/24 on eth0
OK   DNS answers on the LAN address
OK   uplink adapter uplink0: missing, as this case expects
OK   kubelab-edge-liveness.service failed on the missing uplink
INFO failed scheduled runs nobody was paged for: node-backup-ship.service
OK   no failed unit
```

The boot took 2 min 47 s of userspace against 30 s in T1/T2. `systemd-analyze critical-chain` puts `network.target` at 1 min 31.6 s: netplan's `netplan-wpa-uplink0.service` waited the default 90 s device timeout for `uplink0` (`Job sys-subsystem-net-devices-uplink0.device/start timed out` at 99.4 s, then `Dependency failed for netplan-wpa-uplink0.service`). docker, the LAN DNS containers and tailscaled started after it. The rest of the 2 min 47 s is `node-backup-ship.service` (2 min) and `tailscale-watchdog.service` (1 min), oneshots ending on their own timeouts.

#### #2797 provisioned, 2026-10-29 (`make provision NODE=rpi4 ENV=prod BOOTSTRAP=1 TAGS=gateway` from the branch)

First run `changed=3`: the boot check, the drop-in directory, the drop-in; the `reload systemd` handler ran. Second run `changed=0`. Without a reboot, `make edge-boot-check` read `OK   wait for uplink0 at boot bounded (10s; systemd's default 1min 30s)`; the same unit read `1min 30s` before the provision.

#### T1 warm reboot on #2797, 2026-10-29

```text
INFO Startup finished in 7.234s (kernel) + 29.677s (userspace) = 36.912s
INFO ruleset loaded at 9.8s, systemd-networkd started at 12.8s, network.target reached at 13.0s
OK   wait for uplink0 at boot bounded (10s; systemd's default 1min 30s)
```

Every other line `OK`, `no failed unit`. The adapter's device job started at 8.70 s and the device was found at 12.84 s (4.1 s of the 10 s bound); `netplan-wpa-uplink0.service` started at 12.89 s.

#### T3 again on #2797, 2026-10-29 (dongle unplugged, power cut)

```text
INFO Startup finished in 7.590s (kernel) + 31.635s (userspace) = 39.226s
OK   boot finished
INFO ruleset loaded at 10.1s, systemd-networkd started at 13.1s, network.target reached at 19.3s
OK   wait for uplink0 at boot bounded (10s; systemd's default 1min 30s)
OK   uplink adapter uplink0: missing, as this case expects
WAIT kubelab-edge-liveness.service failed on the missing uplink: not yet, 0 of 3 misses counted
OK   no failed unit
```

Userspace drops from 2 min 47 s (T3 before the fix) to 31.6 s; `network.target` from 99.4 s to 19.3 s (`systemd-analyze critical-chain` reads `network.target @11.724s`). `netplan-wpa-uplink0.service` is inactive with `Result=success`, and the device unit carries `JobRunningTimeoutUSec=10s`.

The journal lines of the 10 s device timeout could not be read. At 9.97 s journald renamed the uncleanly shut down `system.journal`; four minutes after boot neither that file nor the first 65 s of the boot is in any file, while archived files from 19:02 (3.5 h older) remain, at 18.6M of the 20M cap. Files written around a power cut are vacuumed first, not the oldest (#2702, comment of 2026-10-29).

Rerun after the liveness counted its misses (it failed about 9 min after boot):

```text
OK   uplink adapter uplink0: missing, as this case expects
OK   kubelab-edge-liveness.service failed on the missing uplink
INFO failed scheduled runs nobody was paged for: node-backup-ship.service tailscale-watchdog.service
OK   no failed unit
```

Every other line as above, exit 0. T3 passes on #2797.

#### T3 recovery: dongle replugged, no reboot

The udev rule started the supplicant: `uplink0 UP 172.16.0.251/23`, `netplan-wpa-uplink0.service` active. The first `make edge-boot-check` read `OK lease on uplink0`, `OK default route out uplink0`, `OK kubelab-edge-shaper.service active`, and three FAILs: `tailnet session running`, `subnet route 172.16.1.0/24 primary on the tailnet`, and `failed units: kubelab-notify@kubelab-edge-liveness.service.service`. The last is the outage's own page: the liveness failed at 435 s, and its notifier could not resolve n8n.kubelab.live with no uplink (four attempts, exit 6). The next successful liveness run sent the recovery page (`kubelab-notify-recovered@...` finished at 496.8 s), which clears the failed notifier by design (#2733). A minute later the check passed, exit 0, every line `OK` but `INFO failed scheduled runs nobody was paged for: node-backup-ship.service tailscale-watchdog.service`.

#### T4 no switch cable on #2797, 2026-10-29 (power cut, everything plugged in but `eth0`'s cable), through the tailnet, 10 min after boot

```text
INFO Startup finished in 7.300s (kernel) + 30.097s (userspace) = 37.397s
OK   boot finished
INFO ruleset loaded at 9.6s, systemd-networkd started at 12.6s, network.target reached at 12.9s
OK   ruleset inet kubelab loaded
OK   ruleset loaded before systemd-networkd started
OK   wait for uplink0 at boot bounded (10s; systemd's default 1min 30s)
OK   hardware watchdog armed
OK   hostapd.service active
OK   dnsmasq.service active
OK   docker.service active
OK   tailscaled.service active
OK   kubelab-edge-liveness.timer active
OK   kubelab-edge-lease-check.timer active
OK   kubelab-edge-lease-check.path active
OK   DHCP server listening
OK   wlan0 serves the lab Wi-Fi
OK   container coredns up
OK   container coredns publishes its ports
OK   container pihole up
OK   container pihole publishes its ports
OK   eth0 present without a carrier, as this case expects
OK   LAN address on eth0
OK   route to 172.16.1.0/24 on eth0
OK   DNS answers on the LAN address
OK   lease on uplink0
OK   default route out uplink0
OK   kubelab-edge-shaper.service active
OK   tailnet session running
OK   subnet route 172.16.1.0/24 primary on the tailnet
OK   no failed unit
```

Exit 0. On this cold boot the adapter's device job was queued at 8.72 s (`Expecting device sys-subsystem-net-devices-uplink0.device`) and the kernel renamed the adapter at 12.60 s, 3.9 s later; the warm reboot (T1) took 4.1 s. Both leave about 6 s of the 10 s bound. The persistent journal of this boot again begins at 47.7 s, so the early lines were read from dmesg (#2702).

#### Cable plugged back after T4, 2026-10-29

The first check did not prove it. `make edge-boot-check` read 27 of 27 `OK`, exit 0, with the switch powered off. It ran over the tailnet, and it has no line for `eth0`'s carrier, while the LAN address, route and DNS hold without one since #2769. It cannot tell a cable from none (#2800). The 07:12 run above has the same limit.

Redone over the LAN (`ip route get 172.16.1.1` via `enx00249b1b0d6b`, after `make edge-lan-link`), on the same boot as T4: no reboot came between, and `Startup finished` reads the same. Before it, `make provision NODE=rpi4 ENV=prod BOOTSTRAP=1 TAGS=gateway` from #2804's branch read `changed=1` (the boot check), then `changed=0`.

```text
INFO Startup finished in 7.300s (kernel) + 30.097s (userspace) = 37.397s
OK   boot finished
INFO ruleset loaded at 9.6s, systemd-networkd started at 12.6s, network.target reached at 12.9s
OK   ruleset inet kubelab loaded
OK   ruleset loaded before systemd-networkd started
OK   wait for uplink0 at boot bounded (10s; systemd's default 1min 30s)
OK   hardware watchdog armed
OK   hostapd.service active
OK   dnsmasq.service active
OK   docker.service active
OK   tailscaled.service active
OK   kubelab-edge-liveness.timer active
OK   kubelab-edge-lease-check.timer active
OK   kubelab-edge-lease-check.path active
OK   DHCP server listening
OK   wlan0 serves the lab Wi-Fi
OK   container coredns up
OK   container coredns publishes its ports
OK   container pihole up
OK   container pihole publishes its ports
OK   eth0 has a carrier
OK   LAN address on eth0
OK   route to 172.16.1.0/24 on eth0
OK   DNS answers on the LAN address
OK   lease on uplink0
OK   default route out uplink0
OK   kubelab-edge-shaper.service active
OK   tailnet session running
OK   subnet route 172.16.1.0/24 primary on the tailnet
OK   no failed unit
```

Exit 0. `eth0 has a carrier` is the line the first check lacked. Of the files #2804 changes, the edge runs only `edge-boot-check.sh`, so it changes what the check reads, not what the edge does at boot, and T1 to T4 stand. T4 was judged by its case's own line, `eth0 present without a carrier`, which predates #2804. That the new line fails when a case that expects the cable finds none is `test_without_the_uplink_a_cable_that_is_out_still_fails`.

### B11-EVIDENCE: the homelab switch behind the edge, 2026-10-30

- **Lease.** dnsmasq's journal holds a `DHCPACK(eth0)` for the operator's laptop on the switch, at `172.16.1.91`, through `make edge-lan-link`.
- **Through the uplink.** On 2026-10-27 ace1, bee and ace2 each had a default route through the RPi4 and a 204 from the connectivity probe. On 2026-10-30 ace2's empty image store was refilled through the uplink: 3.42 GB at ace2's NIC over 4.1 hours, with `make provision NODE=ace2 ENV=prod TAGS=agent_stack` ending `failed=0` and a second run reading `changed=0` (#2703).
- **e2e.** At 09:33Z, `make test-e2e ENV=staging` from master `fba90b14`, with the homelab powered: 68 passed, 21 skipped, 0 failed. Open WebUI has no staging route, so its tests skip there by declaration (`skip_in_envs`). Against prod, the same subset (`-k open_webui`) gave 8 passed.
- **The 03:36Z run.** The same command at 03:36Z gave 68 passed, 19 skipped, 2 failed: `test_security_headers_present[open_webui]` and `test_hsts_header[open_webui]` in `tests/e2e/test_security_headers.py`, both refused on ace2's `100.64.0.5:3080`. Those two tests probed ace2 before reading that staging never runs Open WebUI, so ace2's empty image store failed a run of an env that does not target it. At 09:33Z ace2 answered and the same two skipped by declaration, which is how 2 failed and 19 skipped became 21 skipped. The failures were a test defect, not a staging regression, so the tick stands. #2846 reads the declaration first, after which a staging run no longer depends on ace2 for Open WebUI.

### B4-EVIDENCE: the portal login and a stable uplink MAC, 2026-10-30

- The portal login went through `make edge-lan-link ROUTE=1` with the laptop's own Wi-Fi off (2026-10-28, under "Bring-up progress").
- After the hard-reset boots of 2026-10-29, the re-provisions of the same day (`BOOTSTRAP=1`, then `TAGS=gateway`) and the boot that began 2026-10-29T21:50Z, `make edge-status` read:

```text
uplink: up
lease: yes
public resolver: answers
lease resolver: answers
uplink MAC: matches SOPS
```

- The hand changes listed under "Decisions made during implementation" are gone: `nmcli con delete lab-bootstrap` and `nmcli con delete "Wired connection 1"`, run by the operator. The second profile was deleted rather than reverted: it sat on the same adapter as `kubelab-edge-lan`, the profile `make edge-lan-link` renders, and reverted to its defaults it would compete for that adapter and could take the laptop's default route. `kubelab-edge-lan` stayed active and the route to the LAN stayed on the adapter.

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
