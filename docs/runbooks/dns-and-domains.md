---
id: "kubelab-runbook-dns-and-domains"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-08"
updated: "2026-02-27"
owner: manu
---

# DNS and Domains

> **IMPORTANT**: Public DNS records are now managed by Terraform. See [dns-terraform](dns-terraform.md) for the authoritative runbook (add/modify/delete records, bootstrap from zero, disaster recovery).
> This file covers TLS certificate verification and Traefik ACME — NOT DNS record management.

## Current DNS Configuration

**Domains**: `kubelab.live` + `mlorente.dev` (registered at Squarespace/Cloudflare, DNS managed by Cloudflare)

**28 DNS records** managed by Terraform (`infra/terraform/dns/`). Full inventory in [dns-terraform](dns-terraform.md#Records Inventory).

**DNS layers**:
| Layer | Domain | Resolution | Managed by |
|-------|--------|-----------|------------|
| Public | `*.kubelab.live` | Cloudflare → VPS (162.55.57.175) | Terraform |
| Public | `*.mlorente.dev` | Cloudflare → VPS (162.55.57.175) | Terraform |
| Staging | `*.staging.kubelab.live` | Headscale split DNS → CoreDNS → K3s | CoreDNS Corefile |
| Dev | `*.kubelab.test` | `/etc/hosts` → 127.0.0.1 | Makefile |

Nameservers delegated from Squarespace to Cloudflare. SSL mode: Full (strict).

## Prerequisites

- `dig`, `nslookup`, `openssl`, `curl` available
- SSH access to the server running Traefik (for certificate regeneration)
- Docker access on the target server

## Steps

### 1. Verify DNS configuration

```bash
# Verify A records
dig kubelab.live A
dig blog.kubelab.live A
dig api.kubelab.live A

# Verify DNS propagation (use different DNS servers)
nslookup kubelab.live 8.8.8.8
nslookup kubelab.live 1.1.1.1
```

### 2. Verify SSL certificates

```bash
# Verify certificate
openssl s_client -connect kubelab.live:443 -servername kubelab.live

# View expiration dates
echo | openssl s_client -connect kubelab.live:443 2>/dev/null | openssl x509 -noout -dates

# Verify complete chain
curl -vvI https://kubelab.live 2>&1 | grep -E "(SSL|TLS|certificate)"
```

### 3. Regenerate Traefik certificates

```bash
# On the server
docker exec $(docker ps -q -f name=traefik) rm /acme.json
docker restart $(docker ps -q -f name=traefik)

# Verify renewal logs
docker logs $(docker ps -q -f name=traefik) | grep -i acme
```

## Verification

```bash
# Confirm DNS resolves correctly
dig kubelab.live A +short

# Confirm SSL is valid
echo | openssl s_client -connect kubelab.live:443 2>/dev/null | openssl x509 -noout -dates

# Confirm HTTPS endpoints respond
curl -f https://kubelab.live
curl -f https://blog.kubelab.live
curl -f https://api.kubelab.live/health
```

## Rollback

If certificate regeneration fails, restore the previous `acme.json` from backup:

```bash
# Restore from backup (if available)
docker cp /path/to/backup/acme.json $(docker ps -q -f name=traefik):/acme.json
docker restart $(docker ps -q -f name=traefik)
```

If DNS changes were made incorrectly, revert the DNS records at the registrar/DNS provider.

## Related

- [dns-terraform](dns-terraform.md) — Terraform DNS record management (add/modify/delete records, bootstrap, disaster recovery)
- [dns-homelab](dns-homelab.md) — Internal DNS (CoreDNS + Pi-hole for staging)
- [headscale-setup](headscale-setup.md) — Split DNS configuration for VPN clients

## Last tested

2026-02-27 (DNS records verified via `dig` after Terraform import+apply)
