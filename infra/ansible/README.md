 Ansible Infrastructure Automation

Node provisioning for the KubeLab fleet: one playbook per node
(`playbooks/provision-<node>.yml`), each composing shared roles
(`base_system`, `ssh_hardening`, `docker`, `tailscale`, per-service roles).
Configuration is read directly from the SSOT (`infra/config/values/*.yaml`)
via `include_vars` at playbook level — nothing is pre-rendered into
node-specific files.

 Overview

- Inventory: generated dynamically from `networking.*` in `common.yaml` by
  `toolkit infra ansible generate --env <env>`, written to
  `generated/<env>/hosts.yml`. Never hand-edited.
- Provisioning: `make provision NODE=<node> ENV=<env>` runs
  `playbooks/provision-<node>.yml` against the generated inventory.
- Deploys: per-target playbooks (`deploy-vps.yml`, `deploy-k3s.yml`,
  `deploy-dns.yml`, `deploy-harden-nodes.yml`) invoked the same way via
  their own `make deploy-*` targets.
- Roles: `roles/` holds one directory per capability (system hardening,
  Docker, Tailscale, and one role per service the fleet runs).

 Structure

```
infra/ansible/
├── playbooks/
│   ├── provision-<node>.yml          Per-node provisioning (ace1, ace2, aws1,
│   │                                 bee, jetson, rpi3, rpi4, vps)
│   ├── deploy-vps.yml, deploy-k3s.yml, deploy-dns.yml, ...
│   ├── backup.yml / restore.yml      VPS Docker-volume backup/restore
│   ├── maintain.yml                  node_maintenance role entry point
│   └── homelab-dns.yml               DNS resilience, all nodes (see below)
├── roles/                            One role per capability/service
├── generated/<env>/                  Toolkit output (gitignored) — hosts.yml
├── inventories/homelab.yml           Static, Tailscale-IP inventory for the
│                                     homelab-wide playbooks below only
├── requirements.yml                  Ansible Galaxy collections
└── README.md                         This file
```

 Quick Start

```bash
# Install collections
ansible-galaxy collection install -r infra/ansible/requirements.yml

# Generate the inventory for an environment (SSOT: common.yaml)
poetry run toolkit infra ansible generate --env staging

# Provision a node
make provision NODE=rpi4 ENV=staging

# Deploy a target
make deploy-vps ENV=prod
```

See the root `Makefile` (`make help`) for the full list of `provision`/
`deploy-*` targets and their flags (`BOOTSTRAP=1`, `TAGS=`, `CHECK=1`,
`ASK_PASS=1`).

## Homelab-Wide Playbooks

Separate from the per-node provisioning above, there are playbooks that target **all homelab nodes** directly.

### DNS Resilience

Ensures all nodes can resolve critical infrastructure domains (`vpn.kubelab.live`) via `/etc/hosts`, independent of Pi-hole/RPi4 availability. This prevents Tailscale disconnection cascades when RPi4 is down.

```bash
# Inventory (static, Tailscale IPs)
inventories/homelab.yml

# Apply to all nodes (-K prompts for sudo password)
ansible-playbook -i inventories/homelab.yml playbooks/homelab-dns.yml

# Dry-run
ansible-playbook -i inventories/homelab.yml playbooks/homelab-dns.yml --check --diff

# Verify a specific node
ansible -i inventories/homelab.yml kubelab-jet1 -m raw -a "grep vpn.kubelab.live /etc/hosts"
```

**Notes:**
- `-K` required: most nodes need sudo password for `/etc/hosts` (RPi3 has NOPASSWD).
- The inventory uses Tailscale IPs. If a node is already disconnected from Tailscale, fix it manually via SSH over LAN (`ssh <host>-lan`), then run this playbook to prevent recurrence.
- Jetson Nano uses `raw` module (Python 3.6 too old for Ansible modules). Flagged with `legacy_python: true` in inventory.
- Full operational docs: vault `40-runbooks/dns-homelab.md` → "DNS Resilience" section.
