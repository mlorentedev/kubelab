# Terraform DNS — Cloudflare

Manages DNS records for every zone in `dns/zones.json` via the Cloudflare provider.

## Structure

```
infra/terraform/
  dns/
    main.tf              # Provider, data sources, locals
    variables.tf         # Input variables
    records.tf           # Every zone's own records + service records, one per FQDN
    zones.json           # Managed zones: apex -> key, own records, HSTS opt-out
    moved.tf             # State moves from the old per-zone resources
    zone_settings.tf     # Per-zone Cloudflare settings
    outputs.tf           # Service URLs and record counts
    services.json        # Data-driven service catalog
    dns.tfvars           # Zone IDs, VPS IP, TTL
  backend.s3.tfbackend   # Shared backend settings, generated (make sync-terraform-backend)
  .gitignore
  README.md              # This file
```

## How it works

1. `services.json` defines all services with `name`, `zone`, `proxied`, and `environments` fields
2. `zones.json` declares each zone and its own records (`@`, `www`)
3. `main.tf` parses both and filters services by environment
4. `records.tf` creates one record per FQDN via a single `for_each`

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

Then `make tf-dns-plan`, and `make tf-dns-apply` once the plan reads right.

## Credentials

The Cloudflare API token is stored in SOPS (`infra/config/secrets/common.enc.yaml` under `cloudflare.api_token`) and reaches Terraform as `TF_VAR_cloudflare_api_token` in the runner's child process only.

Required token permissions:
- Zone: DNS: Edit
- Zone: Zone: Read
- Zone: Zone Settings: Edit (`zone_settings.tf`)

This token is Terraform's only. Traefik's ACME DNS-01 resolvers read their own,
`cloudflare.acme_dns_token` (Zone: DNS: Edit on the zones the cluster issues for),
so reading the in-cluster `cloudflare-api-token` Secret cannot edit zone settings.
`tests/test_acme_token_split.py` fails if any Ansible file names the Terraform token
again (#2459).

## Running it

```bash
make tf-dns-plan     # init + plan
make tf-dns-apply    # plan, refuse any destroy/replace, then apply that plan
```

Both go through `toolkit infra terraform run dns <action>`
(`toolkit/features/terraform_runner.py`), the only caller of `terraform` in this
repository (`tests/test_terraform_single_entry.py`). It reads the token from SOPS
and hands it to the child process as `TF_VAR_cloudflare_api_token`; nothing is
exported to your shell or written to disk. A destroy the plan proposes is refused
unless you pass `ALLOW_DESTROY=1`.

Do not run `terraform` by hand here, and never decrypt the whole SOPS file to
pull one value out of it: that prints every secret in it to the terminal.

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

Each zone gets the records its `zones.json` entry lists (a root record, and `www`
as a CNAME for `kubelab.live`) plus one A record per `services.json` entry in that
zone, all declared by the single `for_each` resource in `records.tf`. So:

```bash
# What is actually declared, per zone:
python3 -c "import json;[print(r['zone'],r['name'],r['proxied']) for r in json.load(open('dns/services.json'))]"

# What Terraform will manage, counted by the module itself:
toolkit infra terraform run dns output -- record_count   # every managed A/CNAME record
toolkit infra terraform run dns output -- record_urls    # each record's https:// name
```

`mlorente.dev` currently declares **no** service entries — the module manages its
root record only. `staging.*` names are absent from every zone by design: they
resolve over the VPN through Headscale split DNS to RPi4 CoreDNS, never publicly.

**Not managed** by Terraform (manual/third-party): MX (Zoho), CNAME (SendGrid, Beehiiv, Cloudflare tunnels), TXT (SPF, DKIM, DMARC, domain verification).

## State

Every root keeps its state in R2, `kubelab-tfstate/<root>/terraform.tfstate`, with a
locked history copy before and after every run that writes it (ADR-069). Operations, restore included:
`docs/runbooks/terraform-state.md`.
