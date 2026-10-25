---
tags: [spec, tasks, templates]
created: "2026-10-25"
---

# Tasks - NET-005-lab-edge-site-modes

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] (✓ 2026-10-25) Branch `feature/lab-edge-site-modes` from master, worktree outside the repo.
- [x] (✓ 2026-10-25) Read-only baseline of the RPi4 in `verification.md`.
- [x] (✓ 2026-10-25) Prior art reviewed and applied (`verification.md`); NET-006 #2662 filed, NOTIFY-009 #1021 updated.
- [x] (✓ 2026-10-25) The operator approved `proposal.md`, ADR-075 and the names below.
- [x] (✓ 2026-10-25, #2663) **PR 1 (docs):** this spec folder, ADR-075 flipped to `accepted`, and the ADR-028 amendment. `## Knowledge` names ADR-075 and the ADR-028 amendment. The description lists the plaintext SSOT keys task 2 adds (`networking.edge.uplink.{kind,interface,regdomain,channel,bandwidth}`, `networking.edge.lab_wifi.{cidr,gateway,reservations}`, `networking.nodes.<node>.mac`). The pytest-verified `features.json` ids go into `UNWRITTEN` in `tests/test_spec_verifications_select_tests.py`, and each PR removes the ids whose tests it adds.
- [x] (✓ 2026-10-25, #2663) The two `[OPEN]` risks are gates inside the plan (B3 and B7 below), not blockers for freezing it.

### Names to confirm

New identifiers, confirmed by the operator on 2026-10-25:

| What | Proposed | First used in |
|---|---|---|
| The uplink's stable interface name (`.link` `Name=`) | `uplink0` | task 3 |
| SOPS keys (prod) | `networking.edge.lab_wifi.{ssid,psk}`, `networking.edge.uplink.{mac,ssid,psk,portal_domains}` | task 4 |
| Prod probe (CronJob, directory, rules file) | `edge-watcher`, `infra/k8s/base/services/edge-watcher/`, `grafana-alerting/edge-rules.yaml` | task 22 |
| Make targets | `sync-edge-watcher-targets`, `edge-status`, `edge-login-mode`, `edge-lan-link`, `headscale-rejoin`, `edge-psk-rotate`, `edge-psk-retire` | tasks 22-33 |
| Runbook | `docs/runbooks/lab-edge.md` | task 35 |

## Implementation

PRs stay under ~300 changed lines, excluding tests and generated files. Tests run through `make test`. A "watch it fail" step means `make test` reports the new test red for the stated reason before any implementation lands.

### PR 2 — SSOT and secrets

1. [x] (✓ 2026-10-25, #2665) [P] [AC6] [AC3] Test first, `tests/test_edge_ssot.py`, reading `infra/config/values/common.yaml` with `yaml.safe_load`:
   - `networking.edge.uplink` has `kind` in `{wifi_open, wifi_psk, ethernet}`, `interface`, `regdomain`, `channel` and `bandwidth.{down,up}_kbit`. The channel is valid for the regdomain's 2.4 GHz set (1-11 for `US`, 1-13 for `ES`), since hostapd refuses to start on a channel its country forbids;
   - `networking.edge.lab_wifi` has `cidr`, a `gateway` inside it, and reservations whose IP is inside `cidr`;
   - the lab CIDR overlaps neither `networking.lan_cidr` nor the tailnet CIDR;
   - [AC3] the lab CIDR appears in no Tailscale `advertise_routes`, and no trusted-CIDR entry lies inside it (ADR-041). The RFC 1918 supernets already in the list contain it; SEC-036 (#2669) separates them and tests overlap;
   - no key named `ssid`, `psk`, `mac`, `bssid` or `portal_domains` appears under `networking.edge` in any committed values file.

   Watch it fail.
2. [x] (✓ 2026-10-25, #2665) [AC6] Add `networking.edge` to `common.yaml`:
   - the lab Wi-Fi is `10.0.0.0/24`, with rpi3 reserved at `networking.nodes.rpi3.lan_ip`. The gateway is `10.0.0.1`, the old home router's address (confirmed by the operator on 2026-10-25);
   - the uplink is `kind: wifi_open` on the temporary site, with `regdomain: US`;
   - `networking.nodes.rpi4.wifi_lan_ip` becomes the gateway address, and its comment says why.

   Green.
3. [x] (✓ 2026-10-25, #2665) [AC6] Test first, in `tests/test_edge_ssot.py`: `infra/ansible/playbooks/provision-rpi4.yml` carries no literal MAC or IP. The DHCP reservations read `networking.nodes.<node>.mac`, and the gateway vars read `config.networking.edge`. Move the four homelab MACs, and rpi3's, from the playbook and the `common.yaml` comment into `networking.nodes.<node>.mac`. Green.
4. [ ] (the `SecretSpec`s ✓ 2026-10-25, #2665; the values are stored at B1) [P] [AC6] Test first, `tests/test_secrets_catalog_edge.py`: `SECRET_CATALOG` in `toolkit/features/secrets_manager.py` registers, with `envs=("prod",)`, the lab Wi-Fi SSID and PSK, the uplink MAC, and the keys the current `kind` needs: the SSID for `wifi_open`, the SSID and PSK for `wifi_psk`, none for `ethernet`. `SecretSpec` has no optional flag, so a key no current site uses is not registered: the uplink PSK lands with the first `wifi_psk` site, and `portal_domains` with task 31. The test fails when the SSOT's `kind` needs a key the catalog lacks. Add the `SecretSpec`s. Green. Then store the values in `prod.enc.yaml` through `toolkit secrets set ... --env prod --stdin`, without printing anything:
   - the lab SSID and PSK are piped from the RPi4's current netplan over the LAN;
   - the dongle's MAC is read from `ethtool -P` on the host it is plugged into;
   - the uplink SSID is typed by the operator.

   `make secrets-audit` lists them as present.

### PR 3 — Uplink drops, sysctls, resolver, homelab DHCP

This PR loads the drops before any uplink exists. `iifname` matches a name, so rules for `uplink0` are valid before that interface does.

5. [x] (✓ 2026-10-25, #2666) [P] [AC3] Test first, `tests/test_gateway_firewall_render.py`. It renders `infra/ansible/roles/gateway/templates/nftables.conf.j2` through `tests/ansible_jinja.py` and checks:
   - input on the uplink: `ct state established,related` and udp 67→68 pass, and everything else drops;
   - forward: everything from the uplink that is not `established,related` drops, and so does traffic in both directions between the AP interface and `gateway_interface`;
   - masquerade covers the profile's uplink interface;
   - no `flush ruleset`;
   - the forward drops alone stop uplink-to-LAN, uplink-to-AP and uplink-to-Docker-bridge traffic, with nothing taken from ufw.

   Watch it fail.
6. [x] (✓ 2026-10-25, #2666) [AC3] Implement the template. The deploy task validates with `nft -c -f %s` before the handler reloads. Green.
7. [x] (✓ 2026-10-25, #2666) [P] [AC3] Test first, `tests/test_gateway_sysctl_render.py`, covering `templates/99-kubelab-edge.conf.j2`:
   - `rp_filter` is `all=0`, uplink `1`, every other interface `2`;
   - `accept_redirects=0`, `send_redirects=0` and `accept_source_route=0`;
   - `arp_ignore=1` and `arp_announce=2`;
   - `disable_ipv6=1` on the uplink only.

   Implement. Green.
8. [x] (✓ 2026-10-25, #2666) [P] [AC6] [AC1] Test first, `tests/test_gateway_role_tasks.py`: in `roles/gateway/tasks/main.yml`, the resolver is a `template` task. No `shell` task carries `changed_when: false`. Implement `templates/resolv.conf.j2`, replacing the "Set static resolv.conf" shell task. Green.
9. [x] (✓ 2026-10-25, #2666) [AC4] Test first, in `tests/test_gateway_role_tasks.py`: the role allows udp 67 through ufw on `gateway_interface` with `interface_in`. Implement. Green.
10. [x] (✓ 2026-10-25, #2666) [AC1] Test first, in `tests/test_gateway_role_tasks.py`: the gateway role asserts the installed Tailscale is at least 1.96.2 before it loads the sysctls. Implement. Green.
11. [x] (✓ 2026-10-25, #2666, evidence in `verification.md`) [AC4] Live, over the LAN: `make provision NODE=rpi4 ENV=prod BOOTSTRAP=1 TAGS=gateway`.
    - A host on the switch completes a DHCP exchange with the edge. The baseline's fault was the server side (ufw dropped udp 67), so any client shows it; the operator's laptop is re-checked when its AC11 hand changes are undone.
    - `inet kubelab` shows the chains.
    - A second run reports `changed=0`.

    Record it in `verification.md`. The homelab's DHCP works from here on.

### PR 4 — The uplink

12. [x] (✓ 2026-10-25, #2667) [P] [AC6] [AC9] Test first, `tests/test_gateway_uplink_render.py`. For each `kind`, the netplan render binds the profile's interface with DHCPv4 and these settings:
    - `use-routes`, `use-dns`, `use-ntp`, `use-domains` and `use-hostname` all `false`;
    - `dhcp-identifier: mac`;
    - no IPv6.

    It also checks:
    - the gateway drop-in sits in `/etc/systemd/network/10-netplan-<id>.network.d/`, the directory of the file netplan generates for that id, and sets `UseGateway=yes`;
    - the AP interface appears in no netplan file;
    - for every `kind`, `eth0` renders static at `networking.nodes.rpi4.lan_ip`. The RPi4 has no screen, so the LAN is the recovery path and no profile may drop it.

    Watch it fail.
13. [x] (✓ 2026-10-25, #2667) [AC6] [AC5] Implement:
    - `templates/netplan-edge.yaml.j2` and `templates/dhcp-gateway.conf.j2`;
    - the `.link` file `templates/uplink.link.j2`, which matches `PermanentMACAddress` from SOPS and sets `Name=uplink0` and `MACAddressPolicy=none`. It is rendered with `no_log`. `networking.edge.uplink.mac` names the adapter the current `kind` uses: the USB Wi-Fi adapter for `wifi_open` and `wifi_psk`, the USB Ethernet adapter for `ethernet`. Changing `kind` changes that key in the same edit, and the render test fails if a `kind` reaches the template without it;
    - the netplan task runs with `no_log: true` and mode `0600`, since the file holds the uplink SSID and, for `wifi_psk`, its PSK, and `--diff` would print it;
    - the role owns `/etc/netplan/`. It backs up the hand-written file on the host, then removes it;
    - netplan is validated with `netplan generate` before the handler applies it, and the play waits with `wait_for_connection` after the apply, so a profile that cuts the LAN fails visibly. Recovery from that is editing the SD card from another machine; the runbook (task 35) says how.

    Green.
14. [x] (✓ 2026-10-25, #2667) [AC1] [AC3] Test first, in `tests/test_gateway_role_tasks.py`: in `roles/gateway/tasks/main.yml`, the nftables task comes before the netplan task, so an uplink never comes up without its drops. It is green by construction after task 6; the test keeps it so.
15. [x] (✓ 2026-10-25, #2667) [P] [AC1] Test first, in `tests/test_gateway_firewall_render.py`: the masquerade list is derived from `networking.edge.uplink.interface`, not from the old `enx*`/`wlan0` literals in `defaults/main.yml`. Implement. Green.

### PR 5 — The access point

16. [ ] [P] [AC2] Test first, `tests/test_gateway_ap_render.py`:
    - `hostapd.conf` sets `interface=wlan0`, `hw_mode=g`, the profile's `channel`, `country_code` with `ieee80211d=1`, `wpa=2`, `wpa_key_mgmt=WPA-PSK`, `rsn_pairwise=CCMP` and `ieee80211w=0`. It has no `wps_state`, an absolute `wpa_psk_file` path, and an `ssid` from a variable;
    - the PSK file has one `keyid=<id> 00:00:00:00:00:00 <psk>` line per entry, with mode `0600`;
    - a networkd unit for `wlan0` sets the gateway address and `ConfigureWithoutCarrier=yes`;
    - dnsmasq has a second `dhcp-range` on `wlan0` from the lab CIDR, with the AP address as DNS and rpi3's reservation;
    - `hostapd.conf` sets `ctrl_interface`, which `hostapd_cli reload_wpa_psk` (task 17) and the station `keyid` read (task 34) depend on;
    - the role stops, disables and masks `netplan-wpa-wlan0.service` and `wpa_supplicant.service` before it starts hostapd. Removing the home SSID from netplan does not stop a running supplicant, and hostapd cannot take an interface a supplicant holds.

    Watch it fail.
17. [ ] [AC2] Implement:
    - unmask and enable `hostapd`;
    - the templates, rendered with `no_log`;
    - handlers: `hostapd_cli reload_wpa_psk` for the PSK file, and a restart for the config;
    - ufw allows udp 67 on `wlan0`;
    - the regulatory domain persists through `cfg80211 ieee80211_regdom`.

    Green.

### PR 6 — Collision detection and shaping

18. [ ] [P] [AC7] Test first, `tests/test_edge_lease_check.py`. Feed `roles/gateway/files/edge-lease-check.sh` lease fixtures (address, gateway, routes) and the CIDRs from the SSOT:
    - each collision kind exits non-zero with a message naming the kind;
    - a clean lease exits 0.

    Watch it fail.
19. [ ] [AC7] Implement the script. A systemd path unit watches networkd's lease directory and runs it, with `OnFailure=kubelab-notify@%n.service` (the `node_notify` role). Green.
20. [ ] [P] [AC8] Test first, `tests/test_edge_shaper_render.py`:
    - egress is `cake bandwidth <up> nat dual-srchost`;
    - ingress goes through an IFB device with `cake bandwidth <down> nat dual-dsthost ingress`;
    - both rates come from `bandwidth`, scaled below the measured rate;
    - the unit is bound to the uplink device.

    Watch it fail.
21. [ ] [AC8] Implement the shaper unit. Green.

### PR 7 — The prod probe

22. [ ] [P] [AC12] Test first, `tests/test_edge_watcher_targets.py`: the committed `infra/k8s/base/services/edge-watcher/targets.txt` equals the render from the SSOT. It has one `<node> <tailscale_ip> <port>` line for each always-on node behind the edge (rpi4, rpi3). Implement the renderer next to `watcher_targets()` in `toolkit/features/backup_destination.py`, or in its own module, plus `make sync-edge-watcher-targets`. Green.
23. [ ] [AC12] Test first, `tests/test_edge_watcher_probe.py`. Run `probe.sh` under `sh` with a fake `nc`. Every target yields exactly one `{"metric":"edge_probe","node":...,"up":0|1}` line, also on a timeout, a refused connection or a missing `nc`. The probe is never silent about a target. Watch it fail.
24. [ ] [AC12] Implement:
    - `probe.sh`;
    - the CronJob `infra/k8s/base/services/edge-watcher.yaml`, every 5 minutes, with its image pinned through `IMAGE_SOURCES` in `toolkit/scripts/sync_k8s_images.py`, as the R2 watcher's is;
    - the ingress NetworkPolicy in `infra/k8s/base/governance/networkpolicies.yaml`.

    `tests/test_networkpolicy_coverage.py` and `tests/test_spoke_rbac_covers_manifests.py` stay green.
25. [ ] [AC12] Test first, `tests/test_edge_alerting_rules.py`, for `grafana-alerting/edge-rules.yaml`:
    - a per-target rule alerts on `up` grouped by node, with `noDataState: Alerting`, `execErrState: Alerting` and the `page` routing label;
    - a second rule alerts when no `edge_probe` line arrives at all.

    `tests/test_alerting_no_data_is_not_health.py` stays green. Implement. Green.
26. [ ] [AC12] Read the ADR-044 `page` route and check that it repeats until acknowledged. If it does not, extend it through git and `toolkit infra n8n import`, with a test beside the fabric's existing ones. Record which case held.
27. [ ] [AC12] Staging, following the validation flow in `CLAUDE.md`: repoint `targetRevision` after coordinating with the other lanes, run one Job, and read two lines with `up=1`. Revert. After the merge to prod, run one Job and confirm both rules are Normal.

### PR 8 — Self-recovery

28. [ ] [P] [AC13] Test first, `tests/test_edge_recovery_render.py`:
    - `/etc/systemd/system.conf.d/watchdog.conf` sets `RuntimeWatchdogSec=15s`;
    - the liveness service checks that hostapd reports `ENABLED` with `wlan0` up, and that the uplink holds a lease;
    - on failure it reloads `brcmfmac` first and reboots second;
    - a state file caps reboots per hour, so a radio that never recovers cannot cause a boot loop.

    Watch it fail.
29. [ ] [AC13] Implement the units and their timer. Green.

### PR 9 — Edge status and login mode

30. [x] (✓ 2026-10-25) [P] [AC5] Test first, `tests/test_edge_status.py`. The status script, fed recorded responses, classifies the uplink:
    - `204` from a connectivity check bound to the uplink is `up`;
    - a redirect or `200` is `portal`;
    - no answer is `dead`.

    It exits 0 only for `up`, and with a distinct non-zero code for `portal` and for `dead`, so a script can tell them apart. It also reports whether a public resolver and the lease's resolver answer, and whether the uplink MAC matches SOPS, without printing it. `make edge-status` runs it over SSH. Implement. Green.

    Built as `kubelab-edge-status`, run over SSH to the edge's LAN address (the tailnet rides on the uplink it reports on). The script reads the lease file unprivileged, which B3 confirms on the edge.
31. [ ] [AC5] **Built only if B3 finds that only the site's resolver answers before login.** Test first: `make edge-login-mode MODE=on` renders one Pi-hole `server=/<domain>/<lease DNS>` line per portal domain in SOPS. `MODE=off` removes them and runs `docker restart pihole`, as the `coredns` role does: Pi-hole v6's `pihole reloaddns` does not reload dnsmasq configs, and the cache would otherwise keep the portal's answers. This task also registers `portal_domains` in `SECRET_CATALOG`. Implement through the toolkit and the `coredns` role. Green. If B3 shows public resolvers answer, record that and skip this task.

    Not built with task 30: it waits for B3's answer.

### PR 10 — Operator steps as targets

32. [ ] [P] [AC11] Test first, `tests/test_headscale_rejoin.py`, with subprocess mocked: `make headscale-rejoin NODE=<n>`:
    - mints a single-use Headscale pre-auth key that expires within an hour;
    - runs the tailscale role's `tailscale up` only when `tailscale status` is not `Running`;
    - passes every non-default flag from the SSOT (tailscale/tailscale#5597).

    Implement in `toolkit/features/headscale_nodes.py` and `infra/ansible/roles/tailscale/tasks/main.yml`. Green.
33. [ ] [P] [AC11] [AC5] Test first, `tests/test_edge_lan_link.py`: `make edge-lan-link` renders a NetworkManager profile on the operator's laptop, from `networking.lan_cidr`, with DHCP from the RPi4. It has two modes:
    - management: `never-default`, `ignore-auto-dns`, no IPv6;
    - `ROUTE=1`: the RPi4 becomes the default route, for the portal login with the laptop's own Wi-Fi off.

    `REMOVE=1` deletes the profile. Implement. Green. Then undo the hand changes listed in `verification.md`: remove the `lab-bootstrap` profile and revert "Wired connection 1".

### PR 11 — PSK rotation

34. [ ] [AC10] Test first, `tests/test_edge_psk.py`, with I/O mocked:
    - `make edge-psk-rotate` writes a random PSK of at least 24 characters to SOPS. Captured stdout and stderr hold no secret. It renders both PSK entries with distinct `keyid`s and applies rpi3's NetworkManager profile through a `community.general.nmcli` task (`no_log`) in `infra/ansible/roles/rpi3_services`;
    - `make edge-psk-retire` refuses unless hostapd shows rpi3's MAC on the new `keyid` and rpi3 answers over the tailnet. Then it drops the old entry and reloads.

    If B7 found the radio offloads the handshake, the rotate target takes the fallback in ADR-075 D8 instead. Implement in `toolkit/features/edge_psk.py`. Green.

### PR 12 — Reclassification, runbook, lesson

35. [ ] [AC11] [AC5] Runbook `docs/runbooks/lab-edge.md`:
    - a site change, the three human steps, and the portal login through a client routed by the RPi4;
    - the 5-day renewal and the paid plan's expiry, and what Uptime Kuma shows while the portal holds the uplink;
    - the collision response, the login mode, rotation, recovery from the switch, and the uplink stand-in;
    - recovery when a profile cuts the LAN: the SD card's netplan edited from another machine.

    Test first, `tests/test_edge_runbook_commands.py`: every fenced shell command in the runbook starts with `make `. Replace the netplan heredoc in `docs/runbooks/rpi4-bootstrap.md`, fix its `ES` regulatory domain, and update `docs/runbooks/hardware-setup.md`'s topology. Replace the MAC-derived adapter names in `docs/troubleshooting/networking-dns.md` with `enx<MAC>` (ADR-075 C7).
36. [ ] [AC2] Set `networking.nodes.rpi4.location: always-on` and run `make sync-r2-watcher-targets`. Add the RPi4's push monitor if `tests/test_backup_heartbeat_monitors.py` requires one for always-on nodes. `make test` is green.
37. [ ] Housekeeping: write the lesson `docs/lessons/<category>/lesson-NNN-ufw-does-not-govern-forwarded-traffic.md`, which records the false intersection claim and the evidence that refuted it, and add it to the index. Add a Critical-gotchas line to `CLAUDE.md` saying that on the RPi4 edge, `inet kubelab` alone restricts forwarded traffic. Mark `docs/lessons/networking-dns/lesson-110-nftables-masquerade-must-include-wlan0-not-ju.md` superseded by the new lesson, since ADR-075 moves the masquerade off `wlan0`, and correct `docs/runbooks/rpi4-sd-card-provisioning.md`, which still calls `enx*` and `wlan0` uplinks.
38. [ ] Housekeeping, in another repository: point the dotfiles `rpi4-lan` alias at the new `wifi_lan_ip`, as a dotfiles PR.

## Bring-up and live proof

Run at the temporary site in this order, after the PR each step needs. Every result goes into `verification.md`. Each step's result goes under a `### B<n>-EVIDENCE` heading there, because that heading is what the live part of a `features.json` verification looks for.

- [ ] B1. [AC1] Human step 1: the dongle moves to the RPi4, on a USB 2.0 port with an extension cable.
- [ ] B2. [AC1] [AC3] Provision over the LAN with `BOOTSTRAP=1`, through PR 4. The journal shows `inet kubelab` loaded before `uplink0` came up. Then, with the drops still loaded, `networkctl renew uplink0` renews the lease: the journal shows the renewed DHCPv4 lease on `uplink0`, and the B2 evidence records it (AC1).
- [ ] B3. [AC5] **DNS gate.** Before any login, `make edge-status` reports whether a public resolver and the lease's resolver answer. It decides task 31.
- [ ] B4. [AC5] Human step 2: the portal login, from the laptop on the switch with `make edge-lan-link ROUTE=1` and its own Wi-Fi off. Then the uplink's MAC is reported identical after a reboot and a re-provision, by `make edge-status`, before anything is paid.
- [ ] B5. [AC2] Provision the AP (PR 5). Saved devices rejoin. rpi3 takes its reservation, and Kuma's route answers.
- [ ] B6. [AC1] `make headscale-rejoin NODE=rpi4` and `NODE=rpi3` are each a no-op, or they rejoin. The RPi4 advertises `networking.lan_cidr`.
- [ ] B7. [AC10] **On-device multi-PSK check.** Write two wildcard entries and connect a client with the first entry's PSK. Record which entry works and the `keyid` hostapd logs. If only the last works, try `brcmfmac.feature_disable` through `modprobe.d` and record the result. It decides task 34's path.
- [ ] B8. [AC3] [AC7] [AC9] [AC12] The uplink stand-in (the MSI's hotspot):
  - exposure scans over IPv4 and IPv6;
  - hostile DHCP with option 121 and its own DNS;
  - a colliding address and a colliding gateway;
  - a DNS-only block like a portal's, which must page with the phone on cellular;
  - the dongle unplugged, which must page;
  - rpi3 stopped while the RPi4 is up, which must page.
- [ ] B9. [AC8] Connect-time bounds under a bulk upload and a bulk download, each with and without the shaper.
- [ ] B10. [AC13] `modprobe -r brcmfmac` simulates a halt. The lab Wi-Fi returns with no human step.
- [ ] B11. [AC4] A host on the homelab switch gets a DHCP lease from the RPi4 (`DHCPACK(eth0)` in dnsmasq's journal), the homelab nodes reach the internet through the uplink, and `make test-e2e ENV=staging` passes with the homelab powered.
- [ ] B12. [AC1] A second provisioning run reports `changed=0`. Over a 48-hour soak, the kernel log shows no rtw88 reset.
- [ ] B13. [AC1] At the next site: the Ethernet kind, live. The spec stays in `verifying` until then.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes (`make lint`, `make lint-ansible`)
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder
- [ ] Independent adversarial review by an agent that did not implement it, before archive

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.
