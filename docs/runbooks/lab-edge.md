---
id: lab-edge
type: runbook
status: active
created: "2026-10-25"
owner: manu
---

# Lab edge

> Use when: moving the lab to a new site, logging in to a captive portal, answering an edge page, or reaching an edge that fell off the tailnet.

The RPi4 is the lab's edge (ADR-075). Its built-in radio serves the lab Wi-Fi (`networking.edge.lab_wifi`), which is the same at every site. A USB adapter, named `uplink0` by the `gateway` role, is the uplink to whatever network the site offers (`networking.edge.uplink`). Only the uplink changes from one site to the next.

**Every edge change runs over the homelab LAN, from a laptop on the switch.** The tailnet rides on the uplink being changed, so a change made over the tailnet can cut its own session (ADR-075 D7). Join the LAN first:

```bash
make edge-lan-link
```

It adds the NetworkManager profile `kubelab-edge-lan`, which takes an address from the edge's DHCP and routes `networking.lan_cidr` out the wire, ahead of the tailnet. It takes neither the edge's default route nor its DNS, so the laptop keeps its own internet. `STATIC=1` holds a fixed address instead, for when the edge serves no DHCP (a freshly flashed SD card, or a profile that cut the LAN). `REMOVE=1` deletes the profile. It needs NetworkManager, so it runs on the Linux laptop; a Mac has no implementation yet.

The profile does not connect on its own: a cable plugged in again comes up under NetworkManager's default profile, which has no rule, and the LAN traffic leaves through the tailnet again. Run `make edge-lan-link` after every replug. A gateway provision checks the path rather than the address and refuses a run whose packets ride the tailnet, or that has no route to the edge at all, and `make edge-boot-check` says which path it took (#2801).

## The human steps

ADR-075 D9 allows three, and this runbook asks for no others:

1. **Plugging in the adapters**: the uplink adapter in a USB 2.0 port, on an extension cable (a USB 3.0 port interferes with 2.4 GHz), and the LAN cable to the switch.
2. **The captive portal's login and payment.**
3. **Entering the lab PSK** on client devices the lab does not manage.

Everything else is a Make target. Two gaps remain, each ticketed: approving the edge's subnet route on Headscale after a fresh SD card (#2678), and allowlisting a portal's hosts in Pi-hole (#2679).

## Is the uplink up?

```bash
make edge-status
```

The edge runs the check itself, against a connectivity-check URL bound to the uplink, and the target reaches it over SSH at its LAN address. It answers from the switch and from the lab Wi-Fi, not over the tailnet.

Read the state from the `uplink:` line it prints. make turns every failing recipe into exit 2, so through `make edge-status` a portal, a dead uplink and an unknown one all exit 2. The codes below are `toolkit infra edge status`'s, the command the target runs, for a script that needs them.

| `toolkit infra edge status` exit | State | Meaning |
|------|-------|---------|
| 0 | `up` | The connectivity check answered `204`. |
| 2 | `portal` | A redirect or a `200`: a captive portal holds the uplink. Log in (below). |
| 3 | `dead` | No answer, or no DHCP lease on the uplink. |
| 4 | `unknown` | The lease exists but the SSH user cannot read it. Nothing is known about the uplink. |

It also reports whether a public resolver and the lease's resolver answer, and whether the uplink's MAC matches the one in SOPS, without printing either MAC.

## Moving to a new site

1. **Declare the site.** The uplink's kind, regulatory domain, AP channel and shaped bandwidth are `networking.edge.uplink` in `common.yaml`, changed by a PR like any SSOT value. Pick the channel from what the site's spectrum leaves free, and set the bandwidth a little below the uplink's measured rate. What locates the site is in SOPS (`make secrets ENV=prod`): the SSID for a Wi-Fi site, its PSK for `wifi_psk`, and the adapter's MAC, which changes only with the adapter. The first site of a new kind registers that kind's keys in `SECRET_CATALOG`; `tests/test_secrets_catalog_edge.py` fails until it does.

   ```bash
   make secrets ENV=prod
   make secrets-audit
   ```

2. **Render the uplink**, over the LAN:

   ```bash
   make edge-lan-link
   make provision NODE=rpi4 ENV=prod BOOTSTRAP=1 TAGS=gateway
   ```

   The role loads the uplink's drops before it brings the uplink up, so the uplink is never on a shared network unfiltered. On a fresh card at a captive-portal site the run then stops at the AP's packages, with a message saying the archive answers only after the login. That stop is expected. An edge that already has them installed does not stop there.

3. **Check the uplink** with `make edge-status`. `portal` means the login below. At a site whose portal you have not met before, read the two resolver lines first: if only the lease's resolver answers before the login, the login needs the login mode (below).

4. **Finish the provision** once the uplink is `up`. This runs everything else the play holds, and on a fresh card installs the AP:

   ```bash
   make provision NODE=rpi4 ENV=prod BOOTSTRAP=1
   ```

5. **Measure the line and set the shaper.** The bandwidth declared in step 1 is a guess until the uplink is up. Lift it well above the site's rate (`networking.edge.uplink.bandwidth`, by a PR), provision `TAGS=gateway`, then measure twice:

   ```bash
   make edge-measure
   make edge-measure
   ```

   It counts on the uplink adapter, before the shaper. Exit 2 means the shaper bound the window, so the rate is only a lower bound and the shaper has to be lifted further. Set `down_kbit` and `up_kbit` to 90% of the lower reading in each direction, which the target prints, and provision `TAGS=gateway` again. Read the `link:` line first: a low receive rate at good signal is interference, and `networking.edge.uplink.band` can move the uplink to the other band (lesson-680).

6. **Prove the tailnet.** A site is accepted only once the edge's tailnet session is up through it (ADR-075 D7). If the edge is off the mesh, rejoin it:

   ```bash
   make headscale-rejoin NODE=rpi4
   ```

   It mints a single-use, one-hour pre-auth key on Headscale only when the node is off the mesh, and is a no-op otherwise. `NODE=rpi3` runs the same way (#2687), over rpi3's lab Wi-Fi address, so the controller has to reach the lab Wi-Fi.

## Captive portal

The portal authorizes one MAC at a time, and the one it must authorize is the uplink's. The client that logs in therefore has to reach the portal through the edge. A laptop on the switch that keeps its own Wi-Fi up reaches the portal through that Wi-Fi and authorizes its own MAC instead.

**Login, from the switch:**

1. Turn the laptop's own Wi-Fi off.
2. Route the laptop through the edge:

   ```bash
   make edge-lan-link ROUTE=1
   ```

3. Open any plain `http://` page; the portal answers it. Log in and pay (human step 2).
4. Check, then go back to management mode and turn the Wi-Fi back on:

   ```bash
   make edge-status
   make edge-lan-link
   ```

Once the lab Wi-Fi is up, any client on it can do the login the same way, with no `edge-lan-link`: the portal sees only the uplink's MAC.

A portal page that loads only in part is most likely a Pi-hole blocklist hit on one of its hosts. Nothing allowlists them yet (#2679).

**Renewal and expiry.** The free access class expires every 5 days. The paid upgrade is sold by the hour, day, week or month, and expires too. Either way the portal takes the uplink back, and the login is the same as the first one. The uplink's MAC must not change in between: a new MAC needs a new login and a new payment. `make edge-status` checks it against SOPS after every reboot and re-provision.

**What the monitoring shows while the portal holds the uplink:**

- The edge says nothing: HTTPS and the tailnet are both blocked, so it cannot report its own state.
- Prod pages (ADR-075 D6, AC12): its probe reaches the edge over the tailnet, finds it gone, and pages through the ADR-044 fabric. This is the signal that counts. `make alerts` lists what prod has firing.
- Uptime Kuma on rpi3 reads wrong, not just absent. Its HTTP monitors can read UP from the portal's own page, its HTTPS monitors read DOWN, and none of it leaves the lab until the uplink is back, when a stale burst of notifications arrives at once. Ignore that burst; it reports the past.
- A node that booted while the uplink was down has its stacks (Kuma on rpi3, Gitea on bee, Glances, Open WebUI) waiting for its tailnet address. Each stack unit retries every 30 s and recreates its containers once the address exists, so they come back on their own within a minute of the tailnet (#2500). If one has not, `make provision NODE=<node> ENV=prod` starts a unit left failed and recreates a container whose port was never bound.

## Answering an uplink collision page

The edge alerts when its uplink lease falls inside `networking.lan_cidr`, the lab Wi-Fi's CIDR or the tailnet's (`kubelab-edge-lease-check`, posting through `node_notify`). It pages: the unit declares `page` for itself, while the rest of the node keeps `log` (#2684). Routing survives such a lease, because the longer internal prefix wins. The address can still clash with a host on the homelab LAN:

1. Compare the uplink's address with the edge's DHCP pool (`gateway_dhcp_range_start` to `gateway_dhcp_range_end` in the `gateway` role's defaults) and with every `networking.nodes.*.lan_ip`.
2. Outside both: nothing collides today, and the page is a warning about the site.
3. Inside either: a homelab host and the uplink share an address. Renumbering the homelab LAN, NET-006 (#2662), is now urgent.

A gateway inside one of those CIDRs is worse: it leaves the edge with no usable default route, so the edge cannot post. Prod's probe pages for that case instead.

## Login mode

Some sites answer DNS before the login only from their own resolver. The edge's resolver and Pi-hole's upstreams are public, so at such a site the portal's names do not resolve and the login cannot start. The fix is a bounded login mode, in which Pi-hole forwards the portal's domains to the resolver the lease offered and restarts on exit, so no cached portal answer outlives the login (ADR-075 D3).

It is built only once a site needs it (NET-005 task 31), and the temporary site's answer is recorded in the spec's `verification.md` (B3). Until it exists, a site that needs it cannot complete the login through the edge.

## Lab PSK rotation

Not built yet (NET-005 task 34). The lab Wi-Fi still uses the home network's PSK. The design rotates it with an overlap window (ADR-075 D8): the AP accepts both PSKs, rpi3 moves first because the lab Wi-Fi is its only network, and the old PSK is retired only once rpi3 answers over the tailnet on the new one. Do not rotate it by hand in the meantime: rpi3 has no screen, and a rotation that loses it needs its SD card to recover.

## Self-recovery

The radio's firmware can halt, after a weak client or an eighth station, and only a reboot recovers it. The role arms systemd's hardware watchdog, and a liveness timer (`kubelab-edge-liveness.timer`) watches the AP and the uplink: it reloads the driver first, then reboots, once per outage. If the lab Wi-Fi still does not serve after that reboot, the edge holds and keeps paging instead of rebooting again, since the RPi4 is also the homelab's DNS and DHCP. A warm reboot may not bring back a halted radio, and there is no remote power cycle (ADR-075 D5 records it as debt), so an edge that still alerts after its own reboot needs its power cable pulled. A radio that flaps, serving for a check after each boot, clears that hold each time, and only the cap of two reboots an hour bounds it (#2682).

Do not stop hostapd by hand while the liveness timer runs: the ladder reads a stopped hostapd as a halted radio, reloads the driver under you, and at the next miss reboots the edge. There is no target to pause it yet (#2683).

To prove the ladder on the edge itself (NET-005 B10), halt the radio on purpose from the switch:

```bash
make edge-ap-halt
```

It reads the AP's interface and driver from the deployed liveness unit and refuses to inject anything unless the AP is serving. It then unloads the driver, first on its own and, when that is refused, with the modules that hold it, and reads the AP every 20 seconds until it serves again. The lab Wi-Fi, and rpi3 with it, drops for about three minutes, the grace before the reload, so expect rpi3's and the liveness unit's pages. If the reload does not bring the radio back, the next miss reboots the edge, and the command keeps reading through the reboot. It prints both unload results, the ladder's lines, whether the edge rebooted and how long the AP took to serve. `toolkit infra edge ap-halt` exits 0 when the AP serves again, 1 when it does not within 12 minutes, 3 when nothing was injected and 255 when SSH failed before the fault. Through make every non-zero code is 2, so read the `verdict:` line. Then run `make edge-boot-check` and record both outputs under `### B10-EVIDENCE`.

## Reaching the edge from the switch

When the uplink is dead, behind a portal, or misconfigured, the tailnet is gone and the switch is the way in. The edge keeps `eth0` open to the homelab LAN for exactly this.

```bash
make edge-lan-link
make edge-status
```

Add `STATIC=1` if the edge serves no DHCP. From there, a profile is fixed by changing the SSOT or SOPS and re-running `make provision NODE=rpi4 ENV=prod BOOTSTRAP=1 TAGS=gateway`, as in a site move.

## When a profile cuts the LAN

The role checks a new netplan in a scratch root before it replaces the old one, and the play waits for its connection after applying it, so a profile that netplan rejects never lands and one that cuts the LAN fails the run visibly. A profile that netplan accepts can still take `eth0` down, and then the edge answers on nothing the laptop can reach. The recovery is the SD card:

1. Power the edge off and put its SD card in another Linux machine.
2. On the card's `writable` partition, replace `etc/netplan/10-kubelab-edge.yaml` with the minimal `eth0` file in [rpi4-bootstrap](rpi4-bootstrap.md#2a-netplan-the-lan-only), keeping its `0600` mode. The role keeps the files it replaced in `var/backups/kubelab-netplan/`.
3. Boot the edge, join with `make edge-lan-link STATIC=1`, fix the profile, and re-run the provision as in a site move.

## The uplink stand-in

The checks that need a hostile uplink (ADR-075 AC3, AC7, AC9 and AC12: exposure scans, a colliding lease, DHCP option 121 and its own DNS, a DNS-only block like a portal's) need a router the operator controls. The stand-in is the laptop's own Wi-Fi hotspot, with its DHCP server, and joining it is a site move like any other: a `wifi_psk` site whose SSID and PSK are the hotspot's, in SOPS. The first time, that registers the `wifi_psk` keys in `SECRET_CATALOG`. Move back to the real site the same way when the checks are done.

## Hard-reset test

A power cut is the failure the edge meets most, and nothing else exercises its whole boot: the ruleset before the uplink, the AP, DHCP, the DNS containers, the tailnet and its subnet route. The test runs four boots, and after each one `make edge-boot-check` asks the edge whether it brought everything back. The check reads and changes nothing, and prints one line per check (`OK` or `FAIL`) with no host address. `toolkit infra edge boot-check` exits 0 when every check passes, 1 when one fails, 2 when none failed but one cannot be judged yet, and 64 on a usage error. Through make a failure and a wait both exit 2, so read the `FAIL` and `WAIT` lines.

Before each case, `make edge-status` reports the uplink up and `make edge-boot-check` passes. Wait **10 minutes** after power returns before checking, for every case: the liveness timer first runs 5 minutes after boot and fails on its third miss, so a missing uplink fails it about 7 minutes in. Checked sooner, T3's liveness line reads `WAIT` with the minutes left and the check exits 2 rather than failing: run it again then (#2774). Check the boot under test before anything else touches the edge: a provision or a hand fix in between hides what the boot left broken. A restart of `nftables.service` or `systemd-networkd`, by hand or by an unattended upgrade, moves the times the order check reads, so the order is only measured on a boot nothing has restarted since; the role's reload of the ruleset does not move it. The same `INFO` line gives when `network.target` was reached. The check reads from systemd how long the boot waits for the uplink adapter: systemd's default (90 s) is a `FAIL`, because the `gateway` role's bound did not apply and a missing adapter holds `network.target`, docker and tailscaled that long (#2794). It reads the same before and after a reboot, so run it once after a provision to see the bound in place. The check also asks systemd whether the boot finished (`systemctl is-system-running`), which happens once its job table first empties (lesson-653). A boot still starting is judged by its running start jobs, not by the clock: one with a start timeout reads `WAIT` with its timeout, so run the check again after the longest; one with none (`infinity`, a oneshot's default) is a `FAIL` naming it, since nothing ends it (#2776). The roles give every oneshot they ship a start timeout (#2786), so a `FAIL` naming `kubelab-edge-lease-check` or `kubelab-edge-shaper` means the edge has not been provisioned since: `make provision NODE=rpi4 ENV=prod BOOTSTRAP=1 TAGS=gateway`.

| Case | Physical step | Then run | Passes when |
|---|---|---|---|
| T1 warm reboot | none: `make reboot NODE=rpi4 ENV=prod BOOTSTRAP=1 EXTRA='reboot_force=true'` (`BOOTSTRAP=1` reaches the edge over the LAN, as the check does; without the flag the playbook reboots only a node with a reboot pending) | `make edge-boot-check` | every check is `OK` |
| T2 power cut | pull the power for 10 seconds, plug it back | `make edge-boot-check` | every check is `OK` |
| T3 no uplink adapter | unplug the uplink dongle, then cut the power as in T2 | `make edge-boot-check CASE=no-uplink` | the adapter is missing, `kubelab-edge-liveness.service` has failed, and everything else is `OK`. Its page cannot leave the edge without the uplink, so the failed send is expected too: a dead uplink is paged by prod's watcher (#2672). Checked before the liveness grace ends, about 7 min after boot, its line reads `WAIT` instead (#2774) |
| T4 no switch cable | unplug `eth0`'s cable, then cut the power as in T2 | `make edge-boot-check CASE=no-lan VIA=tailnet` | `eth0` has no carrier and everything else is `OK`: its address, its route and the DNS answer on it, dnsmasq, and both DNS containers with their ports in effect |

T4 reaches the edge over the tailnet, since the cable it would use is the one the case took away: run it from a machine with a tailnet session, such as the laptop on the lab Wi-Fi. T3 has a second half: plug the dongle back and wait 2 minutes. The shaper and the lease come back with the adapter, the liveness check's next run closes the incident, and its recovery message reaches the operator channel. `make edge-boot-check` with no case then passes. A timer's run that failed during the outage, such as `node-backup-ship.service`, and its undelivered page are an `INFO` line, not a failure: the unit's own page and recovery report it, and its next good run clears both. Any other failed unit is a finding. T4 holds the fix for #2732: `eth0` keeps its address and route without a carrier (`ignore-carrier`), the boot waits for no interface, and CoreDNS's health port binds loopback (lesson-648). A `FAIL` on the LAN address, its route or a container's ports, or `systemd-networkd-wait-online.service` among the failed units, is that defect back: record the output on #2732. Plug `eth0` back after T4 the same way, and check again with no case: its `eth0 has a carrier` line is the one that says the cable and the switch are back. The address, its route and the DNS answer hold without either, so before #2800 a check with every line `OK` could not tell a cable from none.

Record each case's full output in the spec's `verification.md`, under `### B14-EVIDENCE`, with the case and the date. A `FAIL` line names what the boot did not bring back: read that unit's journal for this boot (`journalctl -b -u <unit>`), and file the cause before re-running the case.

## Uplink soak

The USB uplink's driver (rtw88) is the part least proven on this kernel, so the edge holds a 48-hour soak before it is trusted (NET-005 B12). The soak is the current boot. It passes once the boot has run 48 hours with no reset of the adapter, meaning the adapter dropping off USB or its driver probing it again. A reboot starts the soak again.

```bash
make edge-soak
```

It reads the edge's `kern.log` over the LAN, because the journal there holds about 8 hours (#2807). It prints the boot's resets, its `failed to leave lps state` warnings and its other uplink lines, then a verdict. `toolkit infra edge soak` exits 0 when the soak passed, 1 on a reset, 2 while the boot holds but has not reached 48 hours, and 3 when the log cannot tell: no kernel banner in it, or an rsyslog that did not start with this boot. Through make every non-zero code is 2, so read the `verdict:` line. The LPS warnings are listed and not counted: the operator decides at the end of the soak whether they warrant turning the driver's power saving off, which starts a new soak. The boot's time can be hours early, since the RPi4 has no clock across a power cut (lesson-662); its length comes from the uptime. Record the output at the end under `### B12-EVIDENCE` in the spec's `verification.md`.

## Shaper check

The uplink is shaped both ways so that a homelab host's bulk transfer does not starve a lab Wi-Fi client (NET-005 AC8, B9). `make edge-shape-check` measures it: bee pulls and then pushes `make edge-measure`'s streams for 30 seconds each, while rpi3, a lab Wi-Fi client, times one TCP connect a second. It runs the shaped windows first, then stops `kubelab-edge-shaper.service` for the two unshaped ones, about a minute in which rpi3, Uptime Kuma and anyone on the lab Wi-Fi are slow. The shaper is started again on any error and on Ctrl-C, retried once, and read back (the unit active and CAKE on the uplink). A run killed outright (SIGTERM, SIGKILL, a closed terminal) leaves it stopped: `make edge-boot-check` reports the shaper, and `make provision NODE=rpi4 ENV=prod TAGS=gateway` or a reboot starts the unit again.

```bash
make edge-shape-check              # measure and print each window
make edge-shape-check BOUND_MS=150 # also judge the shaped windows' p95 connect
```

Each window prints the uplink's rate in each direction from the adapter's counters, the load's answered and refused requests, and the client's connect p50, p95, max and failures. `toolkit infra edge shape-check` exits 0 when measured (and within the bound), 1 when a shaped window lost a connect or is over the bound, 3 when a window has no reading (a load whose direction the uplink counters do not show at 1 Mbit/s or more counts as none) or the shaper was not restored, and 255 when the edge did not answer. Through make every non-zero code is 2, so read the `verdict:` line. A `SHAPER NOT RESTORED` verdict names the provision that restores it. Record the output and the bound under `### B9-EVIDENCE` in the spec's `verification.md`.

## Edge alerts

Prod's `edge-watcher` CronJob (`infra/k8s/base/services/edge-watcher.yaml`)
makes one TCP connect every 5 minutes to each target in
`infra/k8s/base/services/edge-watcher/targets.txt`: the edge, and every
always-on node behind it. The list is generated from `networking` in
`common.yaml` by `make sync-edge-watcher-targets`. Each run logs one line per
target:

```json
{"metric":"edge_probe","namespace":"kubelab","node":"rpi4","up":1}
```

The edge cannot page about its own uplink while that uplink is down, so this
probe runs where the edge's failure does not reach. The first step for either
alert is the same: run the probe once now and read its lines.

```bash
make watcher-run NAME=edge-watcher ENV=prod
```

It prints one line per target and exits non-zero when the Job fails.

### Edge target down

`net005-edge-target-down` fires when a target has answered no probe for 10
minutes. One answer clears it.

- **Every target down**: the edge's uplink is the suspect, since the nodes
  behind it reach the tailnet through it. The uplink adapter is unplugged, the
  site's network is down, or a captive portal holds it (before the first login,
  or after the access expired). From a client on the lab Wi-Fi, check whether
  the site's portal page answers.
- **One target down while the others answer**: that node is down or off the
  tailnet. For rpi3, Uptime Kuma's own heartbeats stop too.
- **No lines at all**: see [Edge watcher silent](#edge-watcher-silent). The
  rule pages on no data as well.

### Edge watcher silent

`net005-edge-watcher-silent` fires when no `edge_probe` line arrived for 15
minutes, three runs. The probe prints a line for every target on every run,
so silence is the watcher, never the edge, and the edge's state is unknown.
`make watcher-run` above tells the causes apart:

- it cannot find the CronJob: it was never deployed;
- the Job never starts: an image pull, or the namespace's quota;
- the Job fails with no line: the probe found its targets file missing or
  empty, and says so on stderr;
- the Job prints its lines: the watcher works now, so the schedule is what
  stopped, most likely a suspended CronJob (a Job cannot outlive its 2-minute
  deadline, so none blocks the next). `make pods ENV=prod` shows when the last
  `edge-watcher` pod ran.
