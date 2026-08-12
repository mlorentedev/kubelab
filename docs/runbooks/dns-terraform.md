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
main.tf          ← parses JSON, filters by zone + environment, resolves target
     ↓
records_*.tf     ← for_each creates A records per service
zone_settings.tf ← TLS/HSTS zone settings + CAA records (not from services.json)
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
  main.tf              # Provider config, data sources (zone lookups), locals (JSON parsing + target resolution)
  variables.tf         # cloudflare_api_token (sensitive), zone IDs, vps_ip, dns_ttl
  records_kubelab.tf   # Root A (@), www CNAME, service A records via for_each
  records_mlorente.tf  # Root A, service A records via for_each
  zone_settings.tf     # TLS/HSTS zone settings + CAA records (SEC-AUDIT-001/002/004/006) — not services.json-driven
  outputs.tf           # Service URLs, record counts
  services.json        # Service catalog: name, zone, proxied, environments, target (optional)
  dns.tfvars           # Zone IDs, VPS IP, TTL
  terraform.tfstate    # Local state (gitignored)
  .terraform.lock.hcl  # Provider lock (committed)
```

## Working from a fresh git worktree

The local backend (`terraform.tfstate`, gitignored) lives only in whichever checkout
last ran `terraform init` there — it is NOT shared automatically across worktrees.
Running a bare `terraform init` in a new worktree creates an **empty** state; the
next `apply` would then try to recreate every live Cloudflare record from scratch.

Before running `make tf-dns-plan`/`tf-dns-apply` (or raw `terraform`) from a new
worktree, point its backend at the canonical state file instead:

```bash
cd infra/terraform/dns
terraform init -backend-config="path=<path-to-canonical-checkout>/infra/terraform/dns/terraform.tfstate"
```

`<path-to-canonical-checkout>` is whichever checkout (usually the primary clone, not
a `.worktrees/*` branch worktree) most recently ran terraform here — check
`git worktree list` if unsure which one that is. This only needs doing once per
worktree; after `init`, `make tf-dns-plan`/`tf-dns-apply` work normally.

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
| `target` | node name (optional) | Points the record at `networking.nodes.<name>.tailscale_ip` (via the `node_tailscale_ips` map in `main.tf`) instead of `var.vps_ip`. Absent → unchanged VPS behavior. Used by VPN-only-reachable services with a publicly-resolvable name, e.g. `pihole` → `ace1` (OPS-022). |

2. Plan and review:
```bash
make tf-dns-plan
# Expected output: "Plan: 1 to add, 0 to change, 0 to destroy."
# Verify the record name, type (A), content (VPS IP or target's Tailscale IP), and proxied status
```

3. Apply:
```bash
make tf-dns-apply
# Runs with -auto-approve — the plan above is the real review gate
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

1. Edit `infra/terraform/dns/dns.tfvars`:
```hcl
vps_ip = "NEW.IP.ADDRESS"
```

2. Plan — expect every A record WITHOUT a `target` to show "change" (records with `target` set, e.g. `pihole`, are unaffected — they resolve to their node's Tailscale IP, not `vps_ip`):
```bash
make tf-dns-plan
```

3. Apply — all records update atomically:
```bash
make tf-dns-apply
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
| `true`  | Public-facing, no client-IP requirement: `api` (currently the only one) | CF CDN + DDoS protection, hides real IP, TTL=auto |
| `false` | VPN/internal: vpn, auth, grafana, gitea | Real client IP visible, TTL=300, no CF overhead |

**Warning:** Changing `proxied` from `false` to `true` hides the real VPS IP. Services that need client IP for rate limiting (auth, Authelia) must stay `proxied=false`.

### Remove a service DNS record

1. Delete the entry from `services.json`
2. Plan — expect "1 to destroy":
```bash
make tf-dns-plan
# Expected: "Plan: 0 to add, 0 to change, 1 to destroy."
# Verify it's destroying the correct record
```
3. Apply:
```bash
make tf-dns-apply
```

**Warning:** Removing a DNS record makes the service unreachable. Ensure the service is already decommissioned.

### Move a service between zones

Not directly supported. Delete from old zone + add to new zone in `services.json`, then `plan` → `apply`. Terraform will destroy old + create new (brief DNS gap during TTL propagation).

### Verify DNS resolution

```bash
# Non-proxied records → should return VPS IP directly
dig +short vpn.kubelab.live @1.1.1.1     # → 162.55.57.175 (proxied=false)
dig +short mlorente.dev @1.1.1.1          # → 162.55.57.175

# Proxied records → return Cloudflare IPs (104.x.x.x / 172.x.x.x)
dig +short api.kubelab.live @1.1.1.1     # → 104.21.x.x (CF proxy, proxied=true)

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

## Manual Usage (without make)

```bash
cd infra/terraform/dns

# Extract token from SOPS
export TF_VAR_cloudflare_api_token="$(sops -d ../../config/secrets/common.enc.yaml | grep api_token | awk '{print $2}')"

terraform init          # First time only
terraform plan -var-file=dns.tfvars
terraform apply -var-file=dns.tfvars
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

Update `dns.tfvars` with the zone IDs and new VPS IP if it changed.

### Step 3: Initialize Terraform

```bash
cd infra/terraform/dns
export TF_VAR_cloudflare_api_token="$CF_TOKEN"
terraform init
```

### Step 4a: Fresh start (no existing records)

If the zones are empty (new Cloudflare account or new domains):

```bash
terraform plan -var-file=dns.tfvars    # Review what will be created
terraform apply -var-file=dns.tfvars   # Create all records
```

This creates every record in one pass: root + www + CAA records (both zones, from `zone_settings.tf`) plus every entry in `services.json`. No imports needed. Record count isn't fixed — see `terraform state list` after apply for the live count instead of trusting a number written down here.

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

# 2. Import root + CAA records (zone_settings.tf; not services.json-driven)
terraform import -var-file=dns.tfvars \
  'cloudflare_record.kubelab_root' "$KUBELAB_ZONE/<RECORD_ID>"
terraform import -var-file=dns.tfvars \
  'cloudflare_record.kubelab_www' "$KUBELAB_ZONE/<RECORD_ID>"
terraform import -var-file=dns.tfvars \
  'cloudflare_record.mlorente_root' "$MLORENTE_ZONE/<RECORD_ID>"
terraform import -var-file=dns.tfvars \
  'cloudflare_record.kubelab_caa_letsencrypt' "$KUBELAB_ZONE/<RECORD_ID>"
terraform import -var-file=dns.tfvars \
  'cloudflare_record.kubelab_caa_digicert' "$KUBELAB_ZONE/<RECORD_ID>"
terraform import -var-file=dns.tfvars \
  'cloudflare_record.kubelab_caa_google' "$KUBELAB_ZONE/<RECORD_ID>"
terraform import -var-file=dns.tfvars \
  'cloudflare_record.mlorente_caa_letsencrypt' "$MLORENTE_ZONE/<RECORD_ID>"
terraform import -var-file=dns.tfvars \
  'cloudflare_record.mlorente_caa_digicert' "$MLORENTE_ZONE/<RECORD_ID>"
terraform import -var-file=dns.tfvars \
  'cloudflare_record.mlorente_caa_google' "$MLORENTE_ZONE/<RECORD_ID>"

# 3. Import service records (for_each uses service name as key — check
#    services.json for the current list; mlorente has zero entries today,
#    so the mlorente_svc for_each is empty and needs no imports)
terraform import -var-file=dns.tfvars \
  'cloudflare_record.kubelab_svc["api"]' "$KUBELAB_ZONE/<RECORD_ID>"
terraform import -var-file=dns.tfvars \
  'cloudflare_record.kubelab_svc["gitea"]' "$KUBELAB_ZONE/<RECORD_ID>"
# ... repeat for each service in services.json

# 4. Verify zero drift
terraform plan -var-file=dns.tfvars
# MUST show "No changes" — if drift, adjust .tf to match reality
```

### Step 5: Verify DNS resolution

```bash
dig +short api.kubelab.live @1.1.1.1     # proxied=true → CF proxy IPs (104.x.x.x / 172.x.x.x)
dig +short mlorente.dev @1.1.1.1          # → VPS IP
dig +short vpn.kubelab.live @1.1.1.1      # proxied=false → VPS IP directly
```

### Step 6: Verify the Makefile targets

```bash
make tf-dns-plan   # Should work without manual token setup — pulls from SOPS via `toolkit secrets show`
```

## Disaster Recovery

### Recover state (tfstate lost, records intact)

Follow **Step 4b** above. Records still exist in Cloudflare — just need re-import.

### Rollback DNS for K3s migration (ADR-015)

The `vps_ip` variable makes rollback a one-liner:
```bash
# If K3s migration fails → revert IP to original VPS
# Edit dns.tfvars → vps_ip = "162.55.57.175"
make tf-dns-apply
```

## Records Inventory

This table is a hand-maintained copy of the state — it has gone stale in exactly this
way more than once (see `docs/lessons.md`: the yamllint header, the `tls: {}` patch,
this file's own `prod.tfvars` references). The authoritative live list is one command:

```bash
cd infra/terraform/dns && terraform state list
```

`services.json` is the SSOT for which service records exist; `zone_settings.tf`
separately owns the root/CAA records for both zones (not services.json-driven).

### Fixed records (both zones, from `zone_settings.tf` + `records_*.tf` — rarely change)

| Record | Zone | Type | Notes |
|--------|------|------|-------|
| @ (root) | kubelab.live | A | `var.vps_ip` |
| www | kubelab.live | CNAME → kubelab.live | |
| @ (root) | mlorente.dev | A | `var.vps_ip` |
| CAA (Let's Encrypt, DigiCert, Google) | both zones | CAA | 3 per zone, restricts cert issuance (SEC-AUDIT-004) |

### Service records — snapshot as of 2026-08-12, verify against `services.json`

**kubelab.live** (12 entries in `services.json`, all zone=kubelab): `api` (proxied), `status`, `auth`, `vpn`, `grafana`, `gitea`, `n8n`, `minio`, `console.minio`, `traefik`, `argo`, `pihole` (`target: ace1` — resolves to a Tailscale IP, not `var.vps_ip`; OPS-022).

**mlorente.dev**: zero entries in `services.json` today — only the fixed root + CAA records above exist for this zone. (The `mlorente_svc` `for_each` is empty until a service targets this zone again.)

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
