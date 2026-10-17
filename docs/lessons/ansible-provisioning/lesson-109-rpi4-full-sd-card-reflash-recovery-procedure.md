---
id: lesson-109-rpi4-full-sd-card-reflash-recovery-procedure
type: lesson
status: active
created: "2026-03-14"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# RPi4 full SD card reflash — recovery procedure

**Context:** RPi4 SD card failed. Required full reflash of Ubuntu Server 24.04 LTS arm64 and complete reprovisioning.

**Issues encountered during recovery:**

1. **SSH key mismatch:** Raspberry Pi Imager stored a different SSH key (`mlorentedev@deployment`) than the workstation key (`manu@msi`). Both keys must be in `authorized_keys`. See `40-runbooks/ssh-keys.md`.

2. **Netplan globbing not supported:** `enx*` wildcard in netplan causes `Error in network definition: must not use globbing`. Use the exact interface name (`enx00249b1b0d6b`). nftables DOES support `enx*` — netplan does NOT.

3. **WiFi SSID parsing bug in configure-sd.sh:** The `awk`/`grep` extraction of WiFi credentials from the Imager's `50-cloud-init.yaml` parsed incorrectly, putting `"access-points"` as SSID. Manual edit required.

4. **regulatory-domain matters:** US vs ES affects which WiFi channels are scanned. Set to match your country.

5. **dnsmasq kills WiFi default route:** After `systemctl restart dnsmasq`, the wlan0 default route disappears. Root cause unclear — possibly dnsmasq interferes with DHCP client on wlan0. Fix: `sudo netplan apply` restores the route.

6. **Docker + nftables iptables conflict:** Docker expects iptables chains (`DOCKER-FORWARD`) that nftables flush removes. Fix: `sudo systemctl restart docker` after nftables is loaded — Docker recreates its chains.

7. **resolv.conf chicken-and-egg:** If `resolv.conf` points to `127.0.0.1` (Pi-hole) before Pi-hole is running, DNS fails and nothing can be installed. Set to `8.8.8.8` during provisioning, switch to `127.0.0.1` after Pi-hole is up.

8. **Headscale assigns new IP on re-registration:** Reflashed node gets a new Tailscale IP (`.10` instead of `.5`). Must update: Headscale split DNS config, CoreDNS Corefile, and all references to the old IP. Delete the old node in Headscale.

9. **Headscale route approval syntax (v0.28):** `headscale routes list` doesn't exist. Use `headscale nodes approve-routes -i <ID> --routes <CIDR>`.

10. **`/etc/hosts` VPN fallback critical:** `162.55.57.175 vpn.kubelab.live` MUST exist or Tailscale bootstrap fails (circular dependency). Verify this FIRST on any reflash.

**Correct provisioning order:**
1. Flash Ubuntu Server 24.04 LTS arm64 with Imager (set hostname, user, WiFi, SSH key)
2. Mount SD on PC → add second SSH key + pre-write configs (netplan, nftables, dnsmasq, sysctl, /etc/hosts)
3. Boot RPi4 → verify WiFi IP
4. SSH in → `apt install nftables dnsmasq` → enable services
5. Install Docker → install Tailscale → register with Headscale
6. Approve subnet routes on VPS
7. Deploy Pi-hole + CoreDNS containers
8. Lock resolv.conf → install watchdog timer
9. Update Headscale split DNS if IP changed
10. Force Tailscale re-sync on all clients

**New Tailscale IP:** `100.64.0.10` (was `100.64.0.5`). Updated everywhere: Headscale split DNS, CoreDNS, common.yaml, ansible inventory, Makefile, vault runbooks (dns-homelab, headscale-setup, monitoring, hardware-setup).

**Scripts:** `infra/provisioning/rpi4/` (configure-sd.sh, part1-base-system.sh, part2-services.sh)

**Rule:** This entire process should be an Ansible playbook. Next reflash MUST be automated. See ANSIBLE-004/005 in backlog.
