---
id: adr023-phase1-minipc-provisioning
type: runbook
status: active
created: "2026-03-16"
owner: manu
---

# ADR-023 Phase 1: MiniPC Bare Metal Provisioning

> Step-by-step runbook for re-provisioning Acemagic MiniPCs from Proxmox VMs to Ubuntu Server 24.04 LTS bare metal.

## Prerequisites

- USB stick with Ubuntu Server 24.04.x LTS flashed (already available)
- Physical access to both MiniPCs + monitor + keyboard
- SSH public key from workstation (`~/.ssh/id_ed25519.pub`)
- Ansible playbooks ready in `infra/ansible/playbooks/` (provision-ace1.yml, provision-ace2.yml)
- Ansible inventory regenerated: `toolkit infra ansible generate --env staging` (ace1/ace2 must appear)
- SOPS secrets decryptable: `sops -d infra/config/secrets/common.enc.yaml` exits 0
- SSH key auth verified on both targets: `ssh -i ~/.ssh/id_ed25519 manu@172.16.1.X` works without password

## Order of Operations

1. Provision **ace2** first (Platform Node) — no K3s dependency
2. Provision **ace1** second (K3s staging) — can test with MinIO on ace2 available
3. Run CoreDNS update on RPi4 — point `*.staging.kubelab.live` to new ace1 IP

## Per-Machine Parameters

| Parameter | ace1 (MiniPC1) | ace2 (MiniPC2) |
|-----------|----------------|----------------|
| Role | K3s all-in-one staging | Platform Node (MinIO + GH Runner) |
| Hostname | `ace1` | `ace2` |
| LAN IP | `172.16.1.2/24` | `172.16.1.5/24` |
| Gateway | `172.16.1.1` (RPi4) | `172.16.1.1` (RPi4) |
| DNS | `172.16.1.1` (Pi-hole) | `172.16.1.1` (Pi-hole) |
| Disk | Full disk, no LVM | Full disk, no LVM |
| Username | `manu` | `manu` |
| **OS user note** | SSOT-014: this is the **OS-level** Linux user (`networking.ssh_users.homelab` in `common.yaml`), NOT the Authelia App admin (`apps.auth.admin_username`). Keep as `manu` here unless executing `SSH-RENAME-001`. | (same) |

## Step 1: BIOS Configuration (~2 min)

1. Power on MiniPC, press `DEL` or `F2` to enter BIOS (AMI Aptio)
2. **Advanced → ACPI Settings → State after G3 → S0 State** (auto-power-on after power loss) — already configured
3. **Boot → Boot Option #1 → USB** (temporarily, for installation)
4. Save & Exit

> **Gotcha (Proxmox → bare metal):** The SSD has a Proxmox LVM volume group (`pve`) that blocks the Ubuntu installer. Before selecting storage in the installer, open shell (`Alt+F2`) and run:
> ```bash
> sudo vgremove -f pve
> sudo wipefs -a /dev/sda
> ```
> Then return to installer (`Alt+F1`) and proceed with "Use an entire disk".

## Step 2: Ubuntu Server Installation (~10 min)

Insert the USB and boot. Follow the installer UI:

| Screen | Selection |
|--------|-----------|
| Language | English |
| Installer update | **Skip** (Continue without updating) |
| Keyboard | English (US) — or your preference |
| Installation type | **Ubuntu Server** (not minimized) |
| Network | **Edit IPv4 → Manual** |
| | Subnet: `172.16.1.0/24` |
| | Address: `172.16.1.2` (ace1) or `172.16.1.5` (ace2) |
| | Gateway: `172.16.1.1` |
| | Name servers: `172.16.1.1` |
| | Search domains: `kubelab.live` |
| Proxy | Leave blank |
| Mirror | Default (archive.ubuntu.com) |
| Storage | **Use an entire disk** → select the internal SSD |
| | Uncheck "Set up this disk as an LVM group" |
| | Confirm destructive action |
| Profile | Your name: `manu` |
| | Server name: `ace1` (or `ace2`) |
| | Username: `manu` |
| | Password: your standard password |
| SSH | **Install OpenSSH server** ✓ |
| | **Import SSH identity** → from GitHub: `mlorentedev` (or paste key manually) |
| Featured snaps | **Skip all** — don't select anything |
| | Select "Done" |

Wait for installation to complete (~5-8 min). Select **Reboot Now**. Remove USB when prompted.

## Step 3: Update Workstation SSH Config (~2 min)

Update `~/.ssh/config` on your workstation. Remove old VM entries and add bare metal nodes:

```ssh-config
# Remove these old entries:
#   Host k3s-server / k3s-agent-1 / k3s-agent-2

# Add these:
Host ace1
  HostName 172.16.1.2
  User manu
  IdentityFile ~/.ssh/id_ed25519
  StrictHostKeyChecking accept-new

Host ace2
  HostName 172.16.1.5
  User manu
  IdentityFile ~/.ssh/id_ed25519
  StrictHostKeyChecking accept-new
```

After Tailscale is registered, add the Tailscale IP as an alias or update HostName:

```ssh-config
Host ace1-ts
  HostName ACE1_TAILSCALE_IP
  User manu
  IdentityFile ~/.ssh/id_ed25519
```

> **DR note:** This SSH config is NOT version-controlled (contains local paths).
> Keep a sanitized template in `infra/provisioning/ssh-config.template` for rebuild scenarios.

## Step 4: Post-Install Verification (~2 min)

From your workstation:

```bash
# Test SSH access (use password first time if key didn't import)
ssh ace1
ssh ace2

# If SSH key wasn't imported during install:
ssh-copy-id -i ~/.ssh/id_ed25519.pub manu@172.16.1.X

# Verify basics
hostname
ip addr show | grep 172.16
cat /etc/os-release | grep VERSION
```

## Step 4b: Regenerate Ansible Inventory

The generated inventory must include ace1/ace2 (replaced old k3s-server/agent VMs):

```bash
cd ~/Projects/kubelab
toolkit infra ansible generate --env staging
# Verify:
grep -A2 'ace1\|ace2' infra/ansible/generated/staging/hosts.yml
```

## Step 5: Run Ansible Provisioning (~15 min per machine)

Each playbook starts with a **pre-flight play** that validates SSH + sudo before touching anything.

```bash
# ace2 first (Platform Node — no K3s dependency)
make provision NODE=ace2 ENV=staging

# ace1 second (K3s staging — can test with MinIO on ace2)
make provision NODE=ace1 ENV=staging
```

> **First run (before Tailscale):** If inventory uses Tailscale IPs that aren't assigned yet, override with LAN IP:
> ```bash
> toolkit infra ansible run -p provision-ace2 -e staging -K --extra-vars "ansible_host=172.16.1.5"
> toolkit infra ansible run -p provision-ace1 -e staging -K --extra-vars "ansible_host=172.16.1.2"
> ```

The playbooks will:
- **Pre-flight:** Validate SSH connectivity, sudo, and SSH key existence
- Install base packages, configure timezone, UFW firewall
- Harden SSH (disable password auth, root login)
- Install Docker CE + Compose + buildx
- Install Tailscale and show manual auth instructions
- **ace1 only**: Install K3s, deploy Cloudflare API token Secret (bootstrap), deploy Traefik HelmChartConfig, fetch kubeconfig
- **ace2 only**: Deploy MinIO + GitHub Actions Runner via Docker Compose

## Step 6: Tailscale Registration (~5 min)

After the playbook shows the auth URL:

1. Open the Headscale admin or run on VPS:
   ```bash
   docker exec headscale headscale nodes register --user homelab --key mkey:XXXX
   ```
2. Verify connectivity:
   ```bash
   tailscale status   # on each MiniPC
   tailscale ping ace1  # from workstation
   ```

## Step 7: Update CoreDNS (~2 min)

The staging wildcard must point to ace1's new Tailscale IP:

```bash
# After Tailscale is registered, note ace1's Tailscale IP
# Update common.yaml networking.nodes.ace1.tailscale_ip
# Then redeploy CoreDNS
make deploy TARGET=dns ENV=prod
```

## Step 8: Verify K3s Staging (~5 min)

```bash
export KUBECONFIG=~/.kube/kubelab-staging-config

# Cluster health
kubectl get nodes -o wide
kubectl get pods -A

# Deploy workloads
make deploy-k8s ENV=staging

# Verify services
make test-e2e ENV=staging
```

## Step 9: Verify Platform Services on ace2 (~3 min)

```bash
# MinIO health (from VPN)
curl -f http://172.16.1.5:9000/minio/health/live

# MinIO console (browser, via Tailscale)
# http://ACE2_TAILSCALE_IP:9001

# GitHub Runner (check GitHub repo Settings → Actions → Runners)
# Should show "kubelab-ace2" as online
```

## Step 10: BIOS Cleanup

Set **Boot Option #1** back to internal SSD (remove USB priority).

## Rollback

If anything goes wrong:
- Re-flash USB, reinstall Ubuntu, re-run Ansible
- K3s staging data is not critical (can be rebuilt from Helm charts)
- MinIO data is empty at first provision (no data to lose)

## Time Estimate

| Step | Time |
|------|------|
| BIOS + Install (per machine) | ~15 min |
| Ansible provisioning (per machine) | ~15 min |
| Tailscale + CoreDNS | ~10 min |
| Verification | ~10 min |
| **Total (both machines)** | **~80 min** |
