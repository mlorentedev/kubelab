---
id: runbook-disaster-recovery
type: runbook
status: active
created: "2026-03-15"
owner: manu
---

---
id: runbook-disaster-recovery
type: runbook
status: active
tags: [dr, backup, terraform, ansible]
created: "2026-03-15"
---

# Disaster Recovery Runbook — VPS Full Rebuild

> Rebuild the entire VPS from scratch using Terraform + Ansible + backups.
> Estimated time: ~30 min (bottleneck: DNS propagation + Tailscale reconnection)

## Prerequisites

- Git clone of kubelab repo
- SOPS key (`age` key in `~/.config/sops/age/keys.txt`)
- SSH key pair (`~/.ssh/id_ed25519`)
- Tailscale running on workstation
- Recent backup on old VPS or offsite storage

## Step 1: Create new VPS (Terraform)

```bash
cd infra/terraform/compute
cp compute.tfvars.example compute.tfvars
# Edit compute.tfvars if needed (server_type, location)

# Get Hetzner API token from SOPS
export TF_VAR_hetzner_api_token=$(sops -d ../../config/secrets/common.enc.yaml | yq '.hetzner.api_key')

terraform init
terraform plan -var-file=compute.tfvars
terraform apply -var-file=compute.tfvars
# Note the output: vps_public_ip
```

## Step 2: Update SSOT with new IP

Edit `infra/config/values/common.yaml`:
```yaml
networking:
  vps:
    public_ip: "<NEW_IP>"  # from terraform output
```

## Step 3: Update DNS (Terraform)

```bash
cd infra/terraform/dns
# Update dns.tfvars with new IP
terraform plan -var-file=dns.tfvars
terraform apply -var-file=dns.tfvars
```

Wait for DNS propagation (~5 min with TTL=300).

## Step 4: Provision VPS (Ansible)

```bash
# Regenerate inventory with new IP
toolkit infra ansible generate --env prod

# Full provision: base system + Docker + Tailscale + services
toolkit infra ansible run -p site -e prod
```

This installs: packages, SSH hardening, Docker, Tailscale, Headscale, Traefik routes, CoreDNS.

## Step 5: Restore backups

If backups are on the old VPS (not accessible):
- Restore from Hetzner snapshot, or
- Copy backup archives from offsite storage to new VPS `/opt/backups/`

If backups are accessible:
```bash
toolkit infra ansible run -p restore -e prod -e backup_id=YYYYMMDD_HHMMSS
```

Critical data to restore:
- `/opt/headscale/` — Headscale SQLite DB (node registrations)
- `/opt/traefik/` — ACME certificates (`acme.json`)
- Docker volumes: `headscale_headscale_data`, `monitoring_grafana_data`, etc.

## Step 6: Verify

```bash
# Headscale
curl -k https://vpn.kubelab.live/health

# All Tailscale nodes reconnect automatically (headscale_data restored)

# CoreDNS
dig @100.64.0.10 -p 5353 status.kubelab.live +short

# Uptime Kuma
curl -k https://status.kubelab.live
```

## Step 7: Reconnect K3s (if needed)

K3s nodes connect via Tailscale. Once Headscale is back:
```bash
# On each K3s node, Tailscale auto-reconnects
# Verify: tailscale status

# K3s apps should resume once VPS Traefik is back
kubectl --kubeconfig ~/.kube/kubelab-config get pods -n kubelab
```

## Important Notes

- **Headscale SQLite is critical**: Without it, all nodes lose VPN registration and must re-authenticate
- **ACME certificates**: Without `acme.json`, Traefik re-requests certs from Let's Encrypt (rate-limited to 5/week per domain)
- **Tailscale on VPS**: Must use `--login-server=https://vpn.kubelab.live` with the PUBLIC IP (not Tailscale IP)
- **DNS propagation**: Cloudflare TTL is 300s — plan for 5-10 min delay
- **Backups**: Run `make backup-vps` regularly. Current retention: 3 backups on VPS
