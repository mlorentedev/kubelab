---
id: runbook-disaster-recovery
type: runbook
status: active
tags: [dr, backup, terraform, ansible]
created: "2026-03-15"
owner: manu
---

# Disaster Recovery Runbook — VPS Full Rebuild

> Rebuild the entire VPS from scratch using Terraform + Ansible + backups.
> Estimated time: ~30 min (bottleneck: DNS propagation + Tailscale reconnection)

## Prerequisites

- Git clone of kubelab repo
- SOPS key (`age` key in `~/.config/sops/age/keys.txt`)
- SSH key pair (`~/.ssh/id_ed25519`)
- Tailscale running on workstation
- Access to the R2 restic repositories (credentials in SOPS `backup.r2.*`, escrow in Bitwarden) — see [offsite-backup-restore](offsite-backup-restore.md)

## Step 1: Create new VPS (Terraform)

```bash
# The inputs are the defaults in infra/terraform/compute/variables.tf (server
# type, location, image); change them there, in a commit, not on the command
# line. The Hetzner token comes from SOPS (`hetzner.api_key`) into terraform's
# environment only, through the runner.
make tf-compute-plan
make tf-compute-apply
# Note the output: vps_public_ip
```

A token rejected with "must be exactly 64 characters long" is not a Hetzner
Cloud API token: re-issue it in the Hetzner console and store it with
`poetry run toolkit secrets set hetzner.api_key --env common --stdin`, rather
than debugging Terraform.

## Step 2: Update SSOT with new IP

Edit `infra/config/values/common.yaml`:
```yaml
networking:
  vps:
    public_ip: "<NEW_IP>"  # from terraform output
```

## Step 3: Update DNS (Terraform)

The DNS root reads the VPS IP from `common.yaml`, so Step 2 is the only edit:

```bash
make tf-dns-plan     # expect the apex and www records to move to <NEW_IP>
make tf-dns-apply
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

Node data is backed up by `node_backup` (restic to Cloudflare R2, one repository per node; sources in `backup.sources`, `common.yaml`). There is no restore playbook: restore with restic, following [offsite-backup-restore](offsite-backup-restore.md) — "Restoring — normal case" when SOPS and the repo are available, "Restoring — the disaster case" when they are not. Restore into a scratch directory first, then move the data into place.

Once the node is back, redeploy the pipeline so backups resume: `make backup ENV=prod`.

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

### After restoring Grafana's database: check each account's sign-in link

Grafana matches a returning SSO login only by the OAuth link stored in its
database. It never matches by login, and it no longer matches by email, since
the email-lookup migration flag was removed (#1842). So a restored or partial
database that holds a row without that link locks the row's owner out of SSO,
and the login fails with `user sync failed`. Check it over the break-glass path,
which needs no SSO login:

```bash
make auth-review ENV=prod
```

Every Authelia identity must read `sign-in: Generic OAuth`. `breakglass` reads
`Auth Proxy`, which is correct: it is the local account. If an identity reads
anything else, re-adopt it with a reviewed PR that sets
`GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP=true` in
`infra/k8s/base/services/grafana-config/grafana.env`. Have that user log in
once, confirm `Generic OAuth`, then remove the flag again. Never leave it on:
while it is on, an IdP email that matches a local row takes that row over.

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
- **Backups**: scheduled by `node_backup` timers, not run by hand. `make backup-node NODE=vps ENV=prod` takes one now; `make backup-coverage` shows which nodes R2 covers; `r2-backup-watcher` alerts when a repository stops receiving.
