---
id: "runbook-dns-terraform"
type: runbook
status: active
tags: [kubelab, dns, terraform, cloudflare, runbook]
created: "2026-02-27"
owner: manu
---

# DNS Management with Terraform (Cloudflare)

> Manages A/CNAME records for `kubelab.live` and `mlorente.dev` via Terraform + Cloudflare provider.

## Architecture

```
services.json    ← single source of truth (service list)
     ↓
main.tf          ← parses JSON, filters by zone + environment
     ↓
records_*.tf     ← for_each creates A records per service
     ↓
Cloudflare API   ← via cloudflare/cloudflare provider ~> 4.0
```

**Credentials flow:**
```
SOPS (common.enc.yaml) → cloudflare.api_token → toolkit _get_terraform_env() → TF_VAR_cloudflare_api_token → provider
```

## File Layout

```
infra/terraform/dns/
  main.tf              # Provider config, data sources (zone lookups), locals (JSON parsing)
  variables.tf         # cloudflare_api_token (sensitive), zone IDs, vps_ip, dns_ttl
  records_kubelab.tf   # Root A (@), www CNAME, service A records via for_each
  records_mlorente.tf  # Root A, service A records via for_each
  outputs.tf           # Service URLs, record counts
  services.json        # Service catalog: name, zone, proxied, environments
  prod.tfvars          # Zone IDs, VPS IP, TTL
  terraform.tfstate    # Local state (gitignored)
  .terraform.lock.hcl  # Provider lock (committed)
```

## Daily Operations

> **Golden rule:** Every change follows the same 3-step cycle: **Edit → Plan → Apply**.
> Never `apply` without reviewing `plan` output first.

### Add a new service DNS record

1. Edit `infra/terraform/dns/services.json` — add a new entry to the JSON array:
```json
{
  "name": "newservice",
  "zone": "kubelab",
  "proxied": false,
  "environments": ["prod"]
}
```

**Field reference:**
| Field | Values | Notes |
|-------|--------|-------|
| `name` | subdomain name | Creates `name.kubelab.live` or `name.mlorente.dev` |
| `zone` | `"kubelab"` or `"mlorente"` | Which domain to create the record under |
| `proxied` | `true` / `false` | See proxied decision matrix below |
| `environments` | `["prod"]` | Must include `"prod"` for the record to be created |

2. Plan and review:
```bash
toolkit infra terraform plan --env prod
# Expected output: "Plan: 1 to add, 0 to change, 0 to destroy."
# Verify the record name, type (A), content (VPS IP), and proxied status
```

3. Apply:
```bash
toolkit infra terraform apply --env prod
# Type "yes" when prompted
```

4. Verify:
```bash
dig +short newservice.kubelab.live @1.1.1.1
# Should return VPS IP (162.55.57.175) or Cloudflare proxy IPs if proxied
```

5. **Don't forget:** If the service needs K8s IngressRoutes, those are separate (in `infra/k8s/`). DNS only creates the Cloudflare record pointing to the VPS.

### Add a subdomain with dots (e.g., `console.minio`)

Same as above. Use the full subdomain as `name`:
```json
{"name": "console.minio", "zone": "kubelab", "proxied": false, "environments": ["prod"]}
```
This creates `console.minio.kubelab.live`.

### Change VPS IP address (migration)

1. Edit `infra/terraform/dns/prod.tfvars`:
```hcl
vps_ip = "NEW.IP.ADDRESS"
```

2. Plan — expect ALL A records to show "change":
```bash
toolkit infra terraform plan --env prod
# Expected: "Plan: 0 to add, 28 to change, 0 to destroy."
```

3. Apply — all records update atomically:
```bash
toolkit infra terraform apply --env prod
```

4. Verify propagation (may take up to TTL seconds = 300s for non-proxied):
```bash
dig +short api.kubelab.live @1.1.1.1
dig +short mlorente.dev @1.1.1.1
```

### Toggle Cloudflare proxy on a service

Edit `services.json` → change `"proxied": true/false` → `plan` → `apply`.

**Proxied decision matrix:**
| Proxied | When to use | Effect |
|---------|-------------|--------|
| `true`  | Public-facing: api, blog, wiki, status | CF CDN + DDoS protection, hides real IP, TTL=auto |
| `false` | VPN/internal: vpn, auth, grafana, gitea | Real client IP visible, TTL=300, no CF overhead |

**Warning:** Changing `proxied` from `false` to `true` hides the real VPS IP. Services that need client IP for rate limiting (auth, Authelia) must stay `proxied=false`.

### Remove a service DNS record

1. Delete the entry from `services.json`
2. Plan — expect "1 to destroy":
```bash
toolkit infra terraform plan --env prod
# Expected: "Plan: 0 to add, 0 to change, 1 to destroy."
# Verify it's destroying the correct record
```
3. Apply:
```bash
toolkit infra terraform apply --env prod
```

**Warning:** Removing a DNS record makes the service unreachable. Ensure the service is already decommissioned.

### Move a service between zones

Not directly supported. Delete from old zone + add to new zone in `services.json`, then `plan` → `apply`. Terraform will destroy old + create new (brief DNS gap during TTL propagation).

### Verify DNS resolution

```bash
# Non-proxied records → should return VPS IP directly
dig +short api.kubelab.live @1.1.1.1     # → 162.55.57.175 (or CF proxy IPs if proxied)
dig +short mlorente.dev @1.1.1.1          # → 162.55.57.175

# Proxied records → return Cloudflare IPs (104.x.x.x / 172.x.x.x)
dig +short blog.kubelab.live @1.1.1.1    # → 104.21.x.x (CF proxy)

# Check from multiple resolvers
dig +short api.kubelab.live @8.8.8.8     # Google DNS
dig +short api.kubelab.live @9.9.9.9     # Quad9
```

### Check current Terraform state

```bash
cd infra/terraform/dns
terraform show                            # Full state dump
terraform state list                      # List all managed resources
terraform state show 'cloudflare_record.kubelab_svc["api"]'  # Single record detail
```

## Manual Usage (without toolkit)

```bash
cd infra/terraform/dns

# Extract token from SOPS
export TF_VAR_cloudflare_api_token="$(sops -d ../../config/secrets/common.enc.yaml | grep api_token | awk '{print $2}')"

terraform init          # First time only
terraform plan -var-file=prod.tfvars
terraform apply -var-file=prod.tfvars
```

## Bootstrap from Zero (New VPS / New Provider)

Use this when setting up on a completely new machine or recreating the infrastructure.

### Prerequisites

- Terraform >= 1.5 installed (`brew install terraform` or `apt install terraform`)
- `jq` installed
- Cloudflare account with domains added
- SOPS + age configured (for credential decryption)

### Step 1: Obtain Cloudflare credentials

```bash
# If SOPS secrets already exist:
sops -d infra/config/secrets/common.enc.yaml | grep api_token

# If creating a new API token:
# Cloudflare Dashboard → My Profile → API Tokens → Create Token
# Permissions: Zone:DNS:Edit + Zone:Zone:Read
# Zone Resources: Include → All Zones (or specific zones)
```

### Step 2: Get Zone IDs

```bash
export CF_TOKEN="<your-cloudflare-api-token>"

# List all zones
curl -s "https://api.cloudflare.com/client/v4/zones" \
  -H "Authorization: Bearer $CF_TOKEN" | jq '.result[] | {name, id}'

# Expected output:
# {"name": "kubelab.live", "id": "a708cb04dd4572e76eb6da42cc09507d"}
# {"name": "mlorente.dev", "id": "4d0a0cf660577b845df5df982ad834a9"}
```

Update `prod.tfvars` with the zone IDs and new VPS IP if it changed.

### Step 3: Initialize Terraform

```bash
cd infra/terraform/dns
export TF_VAR_cloudflare_api_token="$CF_TOKEN"
terraform init
```

### Step 4a: Fresh start (no existing records)

If the zones are empty (new Cloudflare account or new domains):

```bash
terraform plan -var-file=prod.tfvars    # Review what will be created
terraform apply -var-file=prod.tfvars   # Create all records
```

This creates all 28 records from scratch. No imports needed.

### Step 4b: Adopt existing records (state rebuild)

If records already exist in Cloudflare but `terraform.tfstate` is lost:

```bash
# 1. List existing records for each zone
KUBELAB_ZONE="a708cb04dd4572e76eb6da42cc09507d"
MLORENTE_ZONE="4d0a0cf660577b845df5df982ad834a9"

curl -s "https://api.cloudflare.com/client/v4/zones/$KUBELAB_ZONE/dns_records" \
  -H "Authorization: Bearer $CF_TOKEN" | jq '.result[] | {name, id, type, content}'

curl -s "https://api.cloudflare.com/client/v4/zones/$MLORENTE_ZONE/dns_records" \
  -H "Authorization: Bearer $CF_TOKEN" | jq '.result[] | {name, id, type, content}'

# 2. Import root records
terraform import -var-file=prod.tfvars \
  'cloudflare_record.kubelab_root' "$KUBELAB_ZONE/<RECORD_ID>"
terraform import -var-file=prod.tfvars \
  'cloudflare_record.kubelab_www' "$KUBELAB_ZONE/<RECORD_ID>"
terraform import -var-file=prod.tfvars \
  'cloudflare_record.mlorente_root' "$MLORENTE_ZONE/<RECORD_ID>"

# 3. Import service records (for_each uses service name as key)
terraform import -var-file=prod.tfvars \
  'cloudflare_record.kubelab_svc["api"]' "$KUBELAB_ZONE/<RECORD_ID>"
terraform import -var-file=prod.tfvars \
  'cloudflare_record.kubelab_svc["blog"]' "$KUBELAB_ZONE/<RECORD_ID>"
# ... repeat for each service in services.json

terraform import -var-file=prod.tfvars \
  'cloudflare_record.mlorente_svc["api"]' "$MLORENTE_ZONE/<RECORD_ID>"
terraform import -var-file=prod.tfvars \
  'cloudflare_record.mlorente_svc["web"]' "$MLORENTE_ZONE/<RECORD_ID>"
# ... repeat for each mlorente service

# 4. Verify zero drift
terraform plan -var-file=prod.tfvars
# MUST show "No changes" — if drift, adjust .tf to match reality
```

### Step 5: Verify DNS resolution

```bash
dig +short api.kubelab.live @1.1.1.1     # Should return VPS IP (or CF proxy IPs if proxied)
dig +short mlorente.dev @1.1.1.1          # Should return VPS IP
dig +short blog.kubelab.live @1.1.1.1     # Should return CF proxy IPs (proxied=true)
```

### Step 6: Verify toolkit integration

```bash
toolkit infra terraform plan --env prod   # Should work without manual token setup
```

## Disaster Recovery

### Recover state (tfstate lost, records intact)

Follow **Step 4b** above. Records still exist in Cloudflare — just need re-import.

### Rollback DNS for K3s migration (ADR-015)

The `vps_ip` variable makes rollback a one-liner:
```bash
# If K3s migration fails → revert IP to original VPS
# Edit prod.tfvars → vps_ip = "162.55.57.175"
toolkit infra terraform apply --env prod --auto-approve
```

## Records Inventory (2026-02-27)

### kubelab.live — 17 records

| Record | Type | Proxied | TTL |
|--------|------|---------|-----|
| @ (root) | A | Yes | auto |
| www | CNAME → kubelab.live | Yes | auto |
| api | A | Yes | auto |
| blog | A | Yes | auto |
| wiki | A | Yes | auto |
| status | A | No | 300 |
| auth | A | No | 300 |

| vpn | A | No | 300 |
| grafana | A | No | 300 |
| loki | A | No | 300 |
| portainer | A | No | 300 |
| gitea | A | No | 300 |
| n8n | A | No | 300 |
| minio | A | No | 300 |
| console.minio | A | No | 300 |
| crowdsec | A | No | 300 |
| traefik | A | No | 300 |

### mlorente.dev — 11 records

| Record | Type | Proxied | TTL |
|--------|------|---------|-----|
| @ (root) | A | No | 300 |
| api, grafana, loki, minio, n8n, portainer, status, traefik, web, wiki | A | No | 300 |

### NOT managed by Terraform

These records exist in Cloudflare but are managed manually (email, tunnels, verification):
- MX records (Zoho Mail)
- CNAME records (SendGrid, Beehiiv, Cloudflare Tunnels for pollex)
- TXT records (SPF, DKIM, DMARC, Google/OpenAI domain verification)
- ACME challenge TXT records (Let's Encrypt)

## Cloudflare API Token

**Location:** `infra/config/secrets/common.enc.yaml` → `cloudflare.api_token`

**Required permissions:**
- Zone: DNS: Edit
- Zone: Zone: Read

**Zone IDs (immutable):**
- kubelab.live: `a708cb04dd4572e76eb6da42cc09507d`
- mlorente.dev: `4d0a0cf660577b845df5df982ad834a9`

## Gotchas

1. **Root record name:** Use FQDN (`kubelab.live`) not `@` in Terraform — the CF provider stores FQDN in state, `@` causes unnecessary replacements on import.
2. **Proxied records ignore TTL:** When `proxied = true`, Cloudflare sets TTL = auto (1). The `ttl` field in Terraform is ignored.
3. **www.kubelab.live is a CNAME**, not an A record. It points to `kubelab.live` (the root A record).
4. **State is local.** If you lose `terraform.tfstate`, records still exist in Cloudflare — just need re-import.
5. **Email records are NOT managed.** MX, SPF, DKIM, DMARC records for Zoho/SendGrid/Beehiiv are manual. Importing them would risk breaking email delivery.
