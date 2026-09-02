# Terraform DNS — Cloudflare

Manages DNS records for `kubelab.live` and `mlorente.dev` via the Cloudflare provider.

## Structure

```
infra/terraform/
  dns/
    main.tf              # Provider, data sources, locals
    variables.tf         # Input variables
    records_kubelab.tf   # kubelab.live root + service records
    records_mlorente.tf  # mlorente.dev root + service records
    outputs.tf           # Service URLs and record counts
    services.json        # Data-driven service catalog
    prod.tfvars          # Zone IDs, VPS IP, TTL
    terraform.tfstate    # Local state (gitignored)
  .gitignore
  README.md              # This file
```

## How it works

1. `services.json` defines all services with `name`, `zone`, `proxied`, and `environments` fields
2. `main.tf` parses `services.json` and filters by zone + environment
3. `records_*.tf` create A records via `for_each` from the filtered service list
4. Root records (`@`, `www`) are defined explicitly outside the loop

## Adding a new service

Edit `services.json`:

```json
{
  "name": "newservice",
  "zone": "kubelab",
  "proxied": false,
  "environments": ["prod"]
}
```

Then: `terraform plan -var-file=prod.tfvars` and `terraform apply -var-file=prod.tfvars`.

## Credentials

The Cloudflare API token is stored in SOPS (`infra/config/secrets/common.enc.yaml` under `cloudflare.api_token`) and injected via toolkit as `TF_VAR_cloudflare_api_token`.

Required token permissions:
- Zone: DNS: Edit
- Zone: Zone: Read

## Toolkit integration

```bash
# Validate config
toolkit infra terraform init prod

# Plan changes
toolkit infra terraform plan --env prod

# Apply changes
toolkit infra terraform apply --env prod

# Destroy (with confirmation)
toolkit infra terraform destroy --env prod
```

The toolkit automatically extracts the Cloudflare API token from SOPS and passes it as `TF_VAR_cloudflare_api_token`.

## Manual usage

```bash
cd infra/terraform/dns
export TF_VAR_cloudflare_api_token="$(sops -d ../../config/secrets/common.enc.yaml | grep api_token | awk '{print $2}')"

terraform init
terraform plan -var-file=prod.tfvars
terraform apply -var-file=prod.tfvars
```

## Records managed

**`services.json` is the list. This file does not restate it** — until 2026-09-01
it did, as two hand-maintained tables, and every row of both was wrong: five
services that no longer had a record (`blog`, `crowdsec`, `loki`, `portainer`,
`wiki`), four real ones missing (`argo`, `home`, `pihole`, `tasks`), a `proxied`
column naming three records when only `api` is proxied, and counts of 17 and 11
against a true 16 and 1.

That drift was not cosmetic. #1406 was opened to *add* a Loki DNS record, and the
reason anyone believed one was owed is that this table listed `loki` among the
managed records. A stale enumeration generates work in the wrong direction, which
is the same failure the `domain:` declarations in `infra/config/values/` produced
(see `tests/test_declared_domains_are_served.py`). Do not re-add a table here.

Each zone gets a root record plus one A record per `services.json` entry in that
zone, declared as a single `for_each` resource — `records_kubelab.tf` also adds
`www` as a CNAME. So:

```bash
# What is actually declared, per zone:
python3 -c "import json;[print(r['zone'],r['name'],r['proxied']) for r in json.load(open('dns/services.json'))]"

# What Terraform will manage, counted by the module itself:
terraform output kubelab_record_count      # root + www + kubelab.live services
terraform output mlorente_record_count     # root + mlorente.dev services
terraform output kubelab_service_urls      # the resulting https:// names
```

`mlorente.dev` currently declares **no** service entries — the module manages its
root record only. `staging.*` names are absent from both zones by design: they
resolve over the VPN through Headscale split DNS to RPi4 CoreDNS, never publicly.

**Not managed** by Terraform (manual/third-party): MX (Zoho), CNAME (SendGrid, Beehiiv, Cloudflare tunnels), TXT (SPF, DKIM, DMARC, domain verification).

## State

Local backend (`terraform.tfstate`). State file is gitignored. To recover state, re-import existing records using `terraform import`.
