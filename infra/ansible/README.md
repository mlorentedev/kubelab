 Ansible Infrastructure Automation

The Ansible playbooks automate server provisioning and Docker Compose deployments for both staging (Raspberry Pi) and production (VPS) environments. The focus is on mirroring compose stacks, applying security hardening, and keeping configuration generation deterministic. Legacy ks content is archived under `.archive/infra/ansible`.

 Overview

- Staging: Raspberry Pi running Docker Compose stacks that mirror production.
- Production: VPS with Docker Compose, backups, and hardened defaults.
- Templates: Minimal set of parametrised templates in `templates/` rendered by `generate-ansible-config.sh`.
- Integration: Plays nicely with `infra/compose` and `edge/dns-gateway` assets.
- Outputs: Inventory, group vars, and playbooks in `generated/<env>/`.

 Structure

```
infra/ansible/
├── generate-ansible-config.sh        Render inventory + vars from templates
├── requirements.txt                  Python dependencies for Ansible
├── templates/                        Jinja-templated config sources
│   ├── ansible.cfg.template          Base Ansible configuration
│   ├── hosts.template.yml            Inventory generator
│   ├── group_vars/
│   │   ├── all.template.yml          Shared settings
│   │   ├── staging.template.yml      Raspberry Pi overrides
│   │   └── prod.template.yml         VPS overrides
│   ├── playbooks/
│   │   ├── main.template.yml         Deploy applications + services
│   │   ├── setup.template.yml        Host bootstrap (Docker, users, firewall)
│   │   ├── backup.template.yml       Backup routines
│   │   └── rollback.template.yml     Controlled rollback procedures
│   └── tasks/
│       ├── setup-system.yml          Common package/system setup
│       ├── setup-docker.yml          Docker Engine installation
│       ├── deploy-compose.yml        Compose deployment tasks
│       ├── deploy-traefik.yml        Traefik configuration deploy
│       └── health-check.yml          Post-deployment verification
└── README.md                         This file
```

> Need the former ks content? It is preserved in `.archive/infra/ansible` alongside rendered examples.

 Quick Start

. Install dependencies
   ```bash
   pip install -r requirements.txt
   ansible-galaxy collection install community.docker
   ```

. Generate configuration
   ```bash
   ./generate-ansible-config.sh staging    Raspberry Pi staging inventory
   ./generate-ansible-config.sh prod       VPS production inventory
   ```

. Deploy
   ```bash
   cd generated/staging
   ansible-playbook -i hosts.yml playbooks/setup.yml
   ansible-playbook -i hosts.yml playbooks/main.yml
   ```

. Verify
   ```bash
   ansible-playbook -i hosts.yml playbooks/main.yml --tags verify
   ```

 Environment Highlights

 Staging (Raspberry Pi)
- Compose stacks pulled from `infra/stacks/{apps|services}/*/compose.base.yml` + `compose.staging.yml`.
- WireGuard and CoreDNS details exposed through `edge/dns-gateway/.env.staging`.
- Lightweight firewall and failban rules tuned for Pi hardware.
- Optional rsync backups to MiniPC build host.

 Production (VPS)
- Same compose definitions with production overrides.
- Automatic firewall hardening and backup rotation.
- Integration hooks for Terraform-provisioned DNS records.

 Workflow with Toolkit

Toolkit commands wrap common Ansible operations:

```bash
poetry run toolkit deployment setup --env staging
poetry run toolkit deployment deploy --env staging
poetry run toolkit deployment setup --env prod
poetry run toolkit deployment deploy --env prod
```

These commands:

. Render templates via `generate-ansible-config.sh`.
. Execute the relevant playbook from the generated directory.
. Collect logs and surface failures via Rich output.

 Contributing

- Keep templates environment-agnostic; prefer variables in group vars.
- Document new variables in `infra/config/values/*.yaml` and toolkit settings.
- Update associated tests under `tests/` when editing generation logic.
- Drop deprecated artefacts into `.archive/infra/ansible` instead of deleting them outright.

With these playbooks the staging Raspberry Pi and production VPS stay aligned while remaining easy to recover and audit.

## Homelab-Wide Playbooks

Separate from the template-generated staging/prod configs, there are playbooks that target **all homelab nodes** directly.

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
- Full operational docs: vault `02-runbooks/dns-homelab.md` → "DNS Resilience" section.
