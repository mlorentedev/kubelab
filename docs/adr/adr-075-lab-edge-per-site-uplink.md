---
id: "adr-075"
type: adr
status: accepted
owner: manu
date: "2026-10-25"
issue: "kubelab#2661"
tags: [architecture, decision, networking, edge, wifi, security, placement]
depends_on: [adr-013-vpn-consolidation, adr-015-vps-k3s-migration-strategy, adr-020-iac-lifecycle-strategy, adr-023-hub-spoke-multicloud-gitops, adr-028-operational-topology, adr-041-agent-fleet-vpn-segmentation, adr-044-unified-notification-routing-fabric, adr-052-cluster-access-transport]
created: "2026-10-25"
---

# ADR-075: The Lab Owns Its Edge; Only the Uplink Changes per Site

## Status

Accepted, 2026-10-25, in the spec's first PR, which also adds the ADR-028 amendment block, so the two never disagree on `master`. Drafted with the operator during NET-005 (kubelab#2661). Spec: `specs/NET-005-lab-edge-site-modes/`.

## Context

The homelab and the operator's personal devices sat behind a home ISP router that did the NAT and the Wi-Fi. The RPi4 was a client of that Wi-Fi, a NAT gateway and DHCP server for the homelab LAN, and the staging DNS gateway (Pi-hole + CoreDNS). ADR-028 §6 classed it on-demand: "When staging is off, RPi4 can be off."

The operator moved. For about four weeks the only network is a hotel's open Wi-Fi behind a captive portal; after that, a new ISP router at the next site. Neither network is the operator's, so neither can be the lab's edge. Measured at the temporary site and on the RPi4 on 2026-10-25 (`specs/NET-005-lab-edge-site-modes/verification.md`):

- **The hotel network:**
  - a captive portal authorizes by client MAC, and the free class expires every 5 days;
  - its paid upgrade is sold by period (hour, day, week, month);
  - DNS works before login, while HTTP and HTTPS are intercepted;
  - the hotel's `172.16.0.0/23` contains the homelab LAN's `172.16.1.0/24`;
  - the uplink measures 3.3 and 1.5 Mbps, read from a laptop. Which figure is the download is re-measured on the RPi4 for AC8.
- **The RPi4's state before any change:**
  - its netplan is hand-written;
  - ufw forwards everything (`DEFAULT_FORWARD_POLICY="ACCEPT"`) and allows 22, 80, 443 and 41641 on every interface;
  - ufw's default-deny input drops every DHCP request on `eth0`, so the homelab LAN has had no working DHCP;
  - Pi-hole and CoreDNS publish on `0.0.0.0`, which ufw cannot restrict (#959).
- **Hardware:**
  - the built-in radio (BCM43455, firmware 7.45.234) can run an access point. Its stock firmware holds about 7 associated stations; its AP-mode management-frame protection is broken through 7.45.251 (raspberrypi/linux#3619), and WPA3/SAE crashes it (raspberrypi/linux#7528);
  - a USB Wi-Fi adapter (RTL8822BU, in-kernel `rtw88_8822bu`) and a USB Ethernet adapter are available;
  - the kernel ships CAKE.
- **Tailnet:** Headscale lists the RPi4's and rpi3's node keys with no expiry.

ADR-022 is the only earlier record of the RPi4's NAT and DHCP duties ("it serves as NAT gateway, dnsmasq DHCP, Pi-hole, CoreDNS"); it is superseded and quoted here as history.

Constraints the decision is held to:

| # | Constraint | Source |
|---|---|---|
| C1 | Every site change is data in the SSOT, never a role fork or a hand edit. | ADR-020, ADR-042 |
| C2 | Nothing is done by hand except declared human steps. | operator, 2026-10-25 |
| C3 | The uplink is hostile: an evil twin of an open SSID is indistinguishable from the real one. | NET-005 |
| C4 | The edge keeps its tailnet session through every uplink, and nothing in it depends on K3s. | ADR-013 addendum, ADR-015 |
| C5 | Personal devices gain no trust on the tailnet or the homelab LAN. | ADR-041 |
| C6 | Nothing always-on depends on an on-demand node. | ADR-068 D1 |
| C7 | The repository is public: nothing that locates a site, or that lets a stranger on the site claim the lab's paid access (the uplink's MAC), is committed. | NET-005 |

## Options Considered

| Option | Verdict | Reconsider when |
|---|---|---|
| **The RPi4 is the edge: one radio is the lab's AP, the uplink is a per-site profile** | **Chosen.** It already does NAT, DHCP and DNS for the homelab; the hardware is owned; the site becomes data. | The station cap or the USB uplink fails its soak (D2). |
| A travel router as the edge, the RPi4 behind it | Rejected: hardware not owned, and a second box duplicates NAT, DHCP and DNS the RPi4 already runs. | The RPi4's radio cannot serve the site (coverage of a flat, more than ~7 stations). |
| The operator's laptop shares its connection | Rejected by the operator: the edge would depend on a laptop being on and in place (C6). | Never for the edge; it is only the test stand-in of D7. |
| Every device joins the site network directly | Rejected: no Pi-hole, one portal login per device MAC, and the homelab unreachable without each device on the tailnet. | — |
| Built-in radio as AP, Cypress minimal firmware (~19 stations) | Rejected for now: it drops 802.11k/v/r and ACS, and overrides a file that package upgrades can overwrite (C1). | A station is refused at the stock cap. |
| USB adapter as AP, built-in radio as uplink | Rejected for now: the AP would depend on rtw88's AP mode, unverified on 6.8, and on USB at every site. | A station is refused at the stock cap, or the uplink fails its soak. |

## Decision

### D1. The lab owns its edge; only the uplink changes per site

The SSOT gains a `networking.edge` block with two parts:

- **`networking.edge.uplink`** describes the current site:
  - its kind: open Wi-Fi, PSK Wi-Fi, or Ethernet;
  - the interface it binds;
  - the regulatory domain;
  - the shaping bandwidth;
  - the AP's fixed 2.4 GHz channel, picked at the site from its spectrum. A fixed channel keeps the rendered config deterministic, where automatic selection would not.
- **`networking.edge.lab_wifi`** is the lab's own network and does not change between sites: its CIDR, its gateway address and its DHCP reservations. It reuses the home network's `10.0.0.0/24`, with the AP on the home router's address and rpi3 reserved at its old address. That CIDR is a common ISP default, so a future uplink may land in it; AC7 reports that. Any client with a static or reserved address keeps working, and so do `networking.nodes.rpi3.lan_ip` and the `rpi3-lan` alias. rpi3 has no screen, so a client that cannot rejoin cannot be fixed by hand. The RPi4's `wifi_lan_ip` becomes the gateway address.

The secret and the site-identifying values live in SOPS, registered in `SECRET_CATALOG` with a real env and pushed by Ansible (ADR-020): the lab PSK, the lab SSID, the uplink adapter's MAC, and any uplink SSID, PSK, BSSID or portal host (C7). The `gateway` role takes all of it through playbook-mapped variables and renders the uplink, the AP, NAT, firewall, resolver and shaping. Moving site edits the uplink block and re-runs provisioning.

The block sits under `networking.*`, not `infra.*` (ADR-036), because it is network addressing and interface binding, not an attribute of a shared service. The path disambiguates `edge`, which already names the Traefik and error-pages layer (top-level `edge:`, ADR-072) and Cloudflare Workers (ADR-049).

### D2. Radios: the built-in radio is the AP, the USB adapter is the uplink

- **AP:** 2.4 GHz, because a Garmin watch among the clients joins only 2.4 GHz. WPA2-PSK with CCMP, no WPS. PMF and WPA3 stay off for the firmware defects in the Context.
- **wlan0:** it is configured by a systemd-networkd unit, because netplan describes access points only for NetworkManager.
- **Station cap:** the operator's clients are typically 5 associated stations and at most 7 (2026-10-25), against a stock cap of about 7. That is accepted, with the cap documented.
- **Uplink:** the USB Wi-Fi adapter, on a USB 2.0 port with an extension cable. The portal's entitlement is bound to its MAC, so a `.link` file pins that MAC by matching the permanent address. The same file gives the adapter a stable interface name. The MAC exists only in SOPS and in the file rendered on the RPi4. The profile binds the stable name, never the kernel's `wlx<mac>` name, which would publish the MAC in `common.yaml`.
- **Ethernet kind:** the uplink is the USB Ethernet adapter.

**Band choices:**
- **The uplink prefers 5 GHz** when the site offers it, so the two radios do not share a band.
- **2.4 GHz costs nothing at the temporary site.** The AP's real throughput (802.11n, 1x1, tens of Mbps) is far above the 3.3/1.5 Mbps uplink, and 2.4 GHz reaches further through walls.
- **At a site with an Ethernet uplink, the USB adapter is free.** A second AP on 5 GHz with the same SSID is the upgrade path there, decided at that site.

The rejected rows above are the fallbacks, triggered by a refused station or a failed 48-hour soak.

### D3. Nothing on the uplink is trusted

**Who owns the firewall.** ufw stays, because `base_system` installs it on every node. ufw governs what the host itself accepts. It does not govern routed or DNAT'd traffic: Tailscale's `ts-forward` and Docker's `DOCKER-USER` and `DOCKER-FORWARD` chains run before ufw's rules in the forward path and accept their own traffic. So for everything forwarded, the `gateway` role's nftables table `inet kubelab` is the control, and its drops must be complete on their own. A drop in any nftables base chain is final whatever its priority. The drops therefore hold over ufw's `DEFAULT_FORWARD_POLICY="ACCEPT"`, over Docker's chains and over Tailscale's.

`inet kubelab` drops:

- **Input:** everything from the uplink except replies to connections the host opened (`ct state established,related`), so untracked and invalid packets drop too. The one exception is DHCP replies (udp 67 to 68), because lease renewals need them. SSH, DNS and the web UIs stay reachable from the homelab LAN, the lab Wi-Fi and the tailnet.
- **Forward:** the same, from the uplink, and everything between the lab Wi-Fi and the homelab LAN (D4).

Traffic delivered to the host must pass both rule sets, so ufw allows DHCP (udp 67) on `eth0` and on the AP interface. That ufw drops it on `eth0` today is why the homelab LAN has had no DHCP. Docker-published ports are DNAT'd before routing and then forwarded, not delivered locally. The forward drop therefore covers them, even with Pi-hole listening on every interface (`listeningMode=ALL`). Binding the containers to internal addresses is not the control: binding Pi-hole to the tailnet address took staging DNS down for ninety minutes on 2026-08-22 (`roles/coredns/templates/docker-compose.yml.j2`).

A rendering test checks that the forward drops in `inet kubelab` are complete by themselves. A test that took ufw's rules as the forward policy would pass a configuration in which Docker forwards everything. ufw's fleet-wide allow for 41641 is dead on the uplink after this. Tailscale needs only outbound traffic there and falls back to DERP. The ruleset says so in a comment, so the allow is not mistaken for an exposure.

The uplink's DHCP lease supplies an address and a default gateway only:

- systemd-networkd runs with `UseRoutes=no` and a drop-in with `UseGateway=yes`, so option 121 is neither requested nor installed (TunnelVision);
- DNS, NTP, domains and hostname are ignored.

The edge itself:

- IPv6 is off on the uplink;
- `rp_filter` is strict on the uplink and loose elsewhere (`all=0`, uplink `1`, others `2`). The kernel takes the larger of `all` and the interface value, and the subnet route over the tailnet is asymmetric. Strict filtering under Tailscale needs version 1.96.2 or later, so the role asserts that floor (the RPi4 runs 1.102.4);
- `arp_ignore=1`, `arp_announce=2`, and no ICMP redirects or source routing (`accept_redirects=0`, `send_redirects=0`, `accept_source_route=0`);
- the resolver is a template the role owns;
- CAKE shapes both directions of the uplink, ingress through an IFB device: `nat dual-srchost` on egress and `nat dual-dsthost` on ingress, with the rate set a little below the measured one. Egress shaping alone cannot help a video call when the queue builds in the download direction;
- upstream DNS stays plaintext: encrypted DNS fails before the portal login, which is exactly when clients need DNS to detect the portal.

**The DHCP deviation is deliberate.** RFC 3442 says a client must ignore option 3 when option 121 is present. With `UseRoutes=no`, networkd requests neither and still installs option 3 (read in `networkd-dhcp4.c`, v255). Keeping the gateway while refusing the routes is the point: TunnelVision's whole attack is option 121.

**Pre-login DNS is a measured gate, with a fallback.** The temporary site answered DNS before login, but that was measured from a laptop using the site's own resolver. Whether a public resolver answers before login is unknown, and the RPi4's resolver and Pi-hole's upstream are both public. D7 measures it from the RPi4. If only the site's resolver answers, the role uses a bounded login mode. Pi-hole forwards the portal's domains (in SOPS) to the resolver the DHCP lease offered, which networkd records without applying, and Pi-hole restarts on exit. It restarts because its cache serves expired answers for up to an hour (`cache.optimizer=3600`), and a stale portal address would outlive the login.

### D4. The lab Wi-Fi and the homelab LAN do not route to each other

Nothing is forwarded between the lab Wi-Fi and `networking.lan_cidr`; devices reach the homelab over the tailnet, as before. The lab Wi-Fi CIDR is not advertised as a subnet route and enters no trusted-CIDR list (C5, ADR-041). The RPi4 keeps advertising `networking.lan_cidr` with the three required Tailscale flags. The homelab LAN's DHCP is allowed in the firewall, on both inside interfaces.

### D5. The RPi4 is always-on, and its SPOF is restated at its new size

By ADR-028's own test the RPi4 now answers yes: rpi3 (always-on) and every personal device reach the internet through it (C6). ADR-028 §6 is amended (see below). ADR-023 already listed it always-on in its power table, so this restores that classification rather than inventing one.

ADR-023 §3.6's conscious SPOF grows from "staging DNS" to "the whole lab's internet access and the homelab's route to the tailnet". It is restated here; ADR-023 is not edited, since its power table already lists the RPi4 as always-on.

**The SPOF recovers itself where it can.** The radio's firmware can halt, after a weak client or an eighth station, and only a reboot recovers it (raspberrypi/firmware#1403). So:

- the role turns on systemd's hardware watchdog (`RuntimeWatchdogSec`, at most 15 seconds). `/dev/watchdog` exists, and today `RuntimeWatchdogUSec=0`;
- a liveness timer watches the AP and the uplink, and escalates: first it reloads the driver, then it reboots.

A remote power cycle is not provided, and it is recorded as debt. A warm reboot may not bring back a halted radio. Prod `*.kubelab.live` stays unaffected, since it resolves through public DNS. The SD card now takes constant writes (Pi-hole, journal), which is accepted. `coredns-custom`'s "skipped when the RPi4 is off" branch (ADR-047) becomes the exception rather than the norm.

### D6. Alerts have two origins, both into the ADR-044 fabric

- **From the edge, when the uplink still carries traffic:** a lease whose address falls inside the homelab LAN, the lab Wi-Fi or the tailnet CIDR. The detecting unit fails, and `node_notify` posts to prod n8n (`tag: page`). A colliding address leaves routing intact, since the longer internal prefix wins. It can still clash with a host that dnsmasq leases the same address on `eth0`. The runbook names the response: check the address against the pool and the reservations, and if it clashes, NET-006 (#2662) becomes urgent. A gateway inside one of those CIDRs is the other case: it leaves the RPi4 with no usable default route, so it cannot post. That case surfaces through the prod probe below.
- **From prod, when the edge cannot speak:** a dead uplink, a portal that has taken the uplink back, or a dead RPi4. A captive or dead uplink blocks HTTPS and the tailnet, so the edge cannot report its own silence. A prod workload probes the edge over the tailnet on a schedule and logs the result. Vector ships it to Loki, and a Grafana rule alerts on failure or on absence (`noDataState: Alerting`), the pattern of `r2-backup-watcher` and OBS-015.

The same probe watches rpi3, whose Uptime Kuma now shares the edge's fate (ADR-023, ADR-028, ADR-062 P2) and goes silent, not just wrong, when the edge dies. The independence rule still holds for prod, which shares nothing with the edge. For the homelab and for Kuma's own voice, the shared fate is accepted and covered by this probe.

**The probe reports every target on every run.** Grafana marks an alert instance whose series disappears as `MissingSeries` and routes it as resolved. `noDataState: Alerting` fires only when the query returns no series at all. A dead rpi3 next to a live RPi4 would therefore read as resolved. So the probe logs one line per target in the SSOT on every run, with the result as a value (`up=0` or `up=1`), and the rule alerts on that value. A second rule alerts when no probe lines arrive at all, which means the pipeline is dead.

**A third signal is local, and only informative.** The edge probes a connectivity-check URL through the uplink, and a `204` against a redirect tells a portal apart from a dead uplink. It cannot report out. It can tell the operator in the room, through a Make target run from a laptop on the lab Wi-Fi. A status page would need a web server on the edge only for this.

The page must reach the operator over a path that does not run through the edge. A push to a phone that falls back to cellular qualifies. A mailbox read from a laptop on the lab Wi-Fi does not. A phone still associated with a dead Wi-Fi may hold back pushes for an app in the background, so the page repeats until it is acknowledged.

### D7. Provisioning cannot cut its own session, and every site proves its tailnet

**Transport.** Edge changes run over the homelab LAN, from the operator's laptop on the switch: `make provision NODE=rpi4 ENV=prod BOOTSTRAP=1`, never over the tailnet that the uplink carries. `eth0` input stays open to the homelab LAN as the recovery path, and every nftables ruleset is checked with `nft -c` before it loads.

**Order.** Each step comes before the one that needs it:

1. Load the uplink's drops (D3), then render the uplink, in the same run. The uplink never comes up on a shared network while ufw still allows 22, 80, 443 and 41641 everywhere. This step needs no new package (nftables, wpa_supplicant, the driver and its firmware are present).
2. Before the login, while the uplink's MAC is still unauthorized, measure whether a public resolver answers or only the site's own does. The result decides whether the login mode of D3 is needed. It is recorded in `verification.md`.
3. The human portal login, from a client whose traffic goes through the RPi4.
4. Install the AP's packages.
5. Bring up the AP.

**Per-site check.** A site's profile is accepted only once the RPi4's tailnet session is up through it (ADR-013 addendum). The fallback is ADR-052's public bastion path.

**Hostile-uplink checks.** Exposure scans and hostile DHCP need a router the operator controls. They use a stand-in, where the operator's laptop runs a hotspot with its own DHCP server, because the temporary site has no spare Ethernet port to stand in for an ISP router.

### D8. One PSK, rotated with an overlap window

The lab PSK exists only in SOPS; the AP and rpi3 render from it. The first rotation replaces the reused home PSK once rpi3 answers over the tailnet. A rotation target runs these steps:

1. It generates the new PSK without printing it.
2. The AP accepts both the old and the new PSK (`hostapd` `wpa_psk_file`, one `keyid=` per entry, reloaded with `hostapd_cli reload_wpa_psk`).
3. It moves rpi3 first, because its only network is this Wi-Fi.
4. A separate, explicit step retires the old PSK. It refuses to run until rpi3 answers over the tailnet on the new PSK, which the `keyid` of its association shows.

The overlap depends on a capability the radio may lack. brcmfmac can offload the AP's 4-way handshake to the firmware, and the firmware holds a single key, so `wpa_psk_file` may be ignored. An on-device check decides it before AC10 is built. The file gets two wildcard entries, and a client connects with the first entry's PSK. If only the last entry works, the offload is active. Then `brcmfmac.feature_disable` is tried. If the overlap cannot work, the fallback keeps the property that matters: rpi3's saved profile is re-keyed over the tailnet while it is still associated, then the AP switches, and rpi3 drops and rejoins within seconds. The retirement gate stays the same.

### D9. The human steps are declared, and nothing else is manual

The runbook names three human steps:

1. plugging in the adapters;
2. the captive portal's login and payment;
3. entering the PSK on unmanaged client devices.

Everything else is a Make target backed by Ansible or the toolkit:

- the LAN provisioning;
- the mesh rejoin, with a short-lived single-use pre-auth key when a node key no longer works;
- the operator's temporary link to the homelab LAN;
- the PSK rotation.

A portal's login is not scripted. It would be code for one property's app, it would hold the guest's name and room in SOPS, and server-side checks cannot be tested without a live capture. Detecting that the portal is back is generic and is in D6.

## Rationale

The RPi4 already holds every function an edge needs except the AP and the hostile-uplink posture, so the change is to configuration, not hardware. Treating the site as data is what makes the next move a one-block edit (C1). Treating the uplink as hostile rather than merely untrusted follows from the open SSID: the edge cannot authenticate the network it joins, so it must not let that network steer it. That excludes routes, resolvers, inbound connections, and anything that reaches Docker's published ports. The two-origin alert design follows from one fact: a captive or dead uplink silences everything behind it, so only something outside the edge can notice it.

## Consequences

- **Positive:**
  - a move is a profile edit plus the declared human steps;
  - the homelab gets working DHCP back;
  - the edge's exposure is set by one ruleset with a default drop, tested by rendering and by a scan from the stand-in;
  - rpi3's monitoring regains an external witness.
- **Negative:**
  - the RPi4 becomes the single point of failure for the whole lab, on an SD card;
  - the station cap leaves little headroom;
  - the USB uplink driver is unproven for 24/7 on kernel 6.8 until its 48-hour soak passes;
  - the homelab LAN still overlaps the temporary site's network. Collisions are detected (D6), not prevented; renumbering is NET-006 (#2662);
  - two firewalls on one host. ufw decides what the host accepts, and `inet kubelab` alone restricts forwarded traffic, because Docker's and Tailscale's chains accept before ufw's. A test holds the forward drops complete, but a reader has to know the split;
  - while the edge is down, prod has no external witness, because Uptime Kuma shares the edge's fate. A dead-man's switch hosted outside the fleet is NOTIFY-009 (#1021);
  - no remote power cycle for a radio that a warm reboot does not recover (D5).
- **Costs:**
  - hardware: none, all of it is already owned;
  - the paid uplink upgrade, if bought: the site's rate per period × the number of periods. The rate is read at the portal and recorded with its date in the spec's `verification.md` (ADR-063 D4).
- **Debt left visible:**
  - the public Docker address pool (#2136) now also routes the lab Wi-Fi clients' traffic for `172.80.0.0/12` into the RPi4's bridges;
  - per-client Pi-hole policy and the guest network are NET-004 (#2363).

## Amendments to other ADRs (applied on acceptance)

- **ADR-028 §6:** the RPi4 moves from on-demand to always-on, with its NAT, DHCP and AP duties recorded. A dated amendment block is added to that ADR.
- **ADR-023 §3.6:** not edited. D5 restates its SPOF.

## References

- Spec: `specs/NET-005-lab-edge-site-modes/` (proposal, verification baseline), kubelab#2661.
- [ADR-013](adr-013-vpn-consolidation.md) (Noise protocol behind inspecting firewalls), [ADR-015](adr-015-vps-k3s-migration-strategy.md), [ADR-020](adr-020-iac-lifecycle-strategy.md), [ADR-022](adr-022-openclaw-agent-deployment.md) (history only), [ADR-023](adr-023-hub-spoke-multicloud-gitops.md) §3.5-3.6, [ADR-028](adr-028-operational-topology.md), [ADR-036](adr-036-shared-infra-namespace.md), [ADR-041](adr-041-agent-fleet-vpn-segmentation.md), [ADR-042](adr-042-reference-architecture.md), [ADR-044](adr-044-unified-notification-routing-fabric.md), [ADR-047](adr-047-cluster-wide-bootstrap-ssot.md), [ADR-052](adr-052-cluster-access-transport.md), [ADR-062](adr-062-platform-identity-model.md), [ADR-063](adr-063-hub-cloud-provider-migration.md) D4, [ADR-068](adr-068-ace2-operator-agent-tooling.md) D1.
- Issues: #959 (Docker publishing bypasses ufw), #2136 (public Docker pool), #2363 (NET-004 guest network), #2662 (NET-006 renumbering), #1021 (NOTIFY-009 off-network dead-man's switch).
- Firmware: raspberrypi/linux#3619 (AP-mode MFP), raspberrypi/linux#7528 (SAE crash), raspberrypi/firmware#1403 (firmware halt in AP mode); systemd v255 `src/network/networkd-dhcp4.c` (`UseGateway` defaults to `UseRoutes`).
- Firewall paths: Docker, "Packet filtering and firewalls" (ufw does not govern published ports); Tailscale `util/linuxfw/iptables_runner.go` (`ts-forward` first in FORWARD); nftables wiki, "Configuring chains" (a drop is final). Tailscale tailscale/tailscale#18860 (strict `rp_filter` from 1.96.2).
- Alerting: Grafana, "Stale alert instances" and "No data and error states" (`MissingSeries` resolves).
- DHCP: RFC 3442 §2 (option 3 ignored when 121 is present); Leviathan Security, TunnelVision (CVE-2024-3661).
- Prior art: OpenWrt Travelmate, GL.iNet's captive-portal login mode, Tailscale's captive-portal docs, and smos/nomad-hotspot (the same radio split). The review of them is in the spec's `verification.md`.
