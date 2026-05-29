---
id: "kubelab-troubleshooting-ssl-certificates"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# SSL/TLS Certificate Issues

Problems related to SSL certificates, HTTPS, and Let's Encrypt in the KubeLab platform.

## Dev: Browser Shows Certificate Error for *.kubelab.test

### Root Cause

One of these:
1. Browser not restarted after `mkcert -install`
2. Dev cert regenerated but Traefik not restarted
3. Old cert was for `*.cubelab.test` (old project name) — needs regeneration

### Diagnostic

```bash
# Verify Traefik is serving the correct cert
openssl s_client -connect localhost:443 -servername mlorente.test </dev/null 2>/dev/null \
  | openssl x509 -noout -issuer -subject

# Should show:
#   issuer=O = mkcert development CA, OU = manu@msi ...
#   subject=O = mkcert development certificate ...
```

### Solution

```bash
# Regenerate cert, reinstall CA, restart Traefik
make regen-certs

# Then restart your browser (required to load new CA)
```

### Prevention

`make regen-certs` handles the full workflow. Run it whenever dev certs expire or after project renames.

---

## Dev: Certificate valid for `*.kubelab.test` but not for `mlorente.test`

### Root Cause

`*.kubelab.test` wildcards only cover one level deep — they do not cover sibling domains like `mlorente.test`. The cert generator previously only included `BASE_DOMAIN` and `*.BASE_DOMAIN`, missing any web app domain that uses a different root (e.g. `mlorente.test` for the portfolio).

### Diagnostic

```bash
# Check what SANs the current cert has
openssl x509 -in infra/config/certs/dev/cert.pem -noout -ext subjectAltName

# Confirm what Traefik is actually serving
openssl s_client -connect localhost:443 -servername mlorente.test </dev/null 2>/dev/null \
  | openssl x509 -noout -ext subjectAltName
# Error: "subjectAltName does not match mlorente.test" → cert missing that domain
```

### Solution

```bash
make regen-certs
# Restart browser after
```

### How it works

`toolkit tools certs generate` calls `_get_default_domains()` in `toolkit/cli/tools.py`, which now reads `APPS_PLATFORM_WEB_DOMAIN` from the env config and appends it automatically if it's not a subdomain of `BASE_DOMAIN`. Fixed 2026-02-25.

---

## Dev: `console.minio.kubelab.test` cert error (multi-level subdomain)

### Root Cause

`*.kubelab.test` only covers **one subdomain level**. `console.minio.kubelab.test` has two levels (`console` + `minio`) — the wildcard does not match it. Same root cause as the `mlorente.test` bug, but this time it's a second-level subdomain within the same base domain.

### Diagnostic

```bash
openssl x509 -in infra/config/certs/dev/cert.pem -noout -ext subjectAltName
# Missing: console.minio.kubelab.test → browser shows cert error
```

### Solution

`_get_default_domains()` now auto-detects any configured `*_DOMAIN` env var that has more than one subdomain level relative to `BASE_DOMAIN` and adds it as an explicit SAN. Fixed 2026-02-25.

```bash
make regen-certs   # picks up console.minio.kubelab.test automatically
```

### Prevention

Any service with a multi-level subdomain (e.g. `console.minio.*`, `admin.gitea.*`) must either:
- Use a single-level subdomain instead (`minio-console.kubelab.test`)
- Or rely on `_get_default_domains()` scanning `*_DOMAIN` env vars — which it now does automatically

---

## Certificate Not Working

### Problem

HTTPS connections fail or browsers show certificate warnings.

### Diagnostic Steps

```bash
# Check Traefik logs for certificate errors
make logs APP=traefik

# Verify DNS resolution
dig kubelab.live
curl -vvI https://kubelab.live

# Check certificate validity
openssl s_client -connect api.kubelab.live:443 -servername api.kubelab.live

# Verify Let's Encrypt rate limits
curl -s https://crt.sh/?q=kubelab.live | jq
```

### Solution

```bash
# Check acme.json permissions
ls -la edge/traefik/data/acme.json
chmod 600 edge/traefik/data/acme.json

# View certificate status
docker exec traefik cat /letsencrypt/acme.json | jq '.Certificates'

# Force certificate renewal
rm edge/traefik/data/acme.json
toolkit edge restart traefik

# Check number of certificates
docker exec traefik cat /letsencrypt/acme.json | jq '.Certificates | length'
```

### Prevention

- Use the Let's Encrypt staging environment first for testing
- Check DNS propagation before deploying
- Wait 1 hour between failed certificate attempts
- Always verify DNS before deploying: `make verify-dns ENVIRONMENT=prod`

## Let's Encrypt Rate Limits

### Problem

Certificate requests fail due to Let's Encrypt rate limiting.

### Diagnostic Steps

```bash
# Check certificate history
curl -s https://crt.sh/?q=kubelab.live | jq
```

### Solution

```bash
# Use staging environment for testing
# certificatesResolvers.letsencrypt.acme.caServer=https://acme-staging-v02.api.letsencrypt.org/directory

# Ensure DNS is correct before requesting certs
dig api.kubelab.live +short

# Remove failed certificates and retry
rm edge/traefik/data/acme.json
chmod 600 edge/traefik/data/acme.json

# Wait for DNS propagation (up to 48h)
watch -n 60 dig api.kubelab.live
```

### Prevention

- Always test with staging CA first
- Verify DNS records resolve correctly before enabling certificate automation
- Document all DNS changes in infrastructure changelog

## Cloudflare DNS Challenge — Zone Not Found

### Problem

Traefik logs show: `cloudflare: failed to find zone kubelab.live.: zone could not be found` when requesting cert for a new subdomain.

### Root Cause

The Cloudflare API token (`CF_DNS_API_TOKEN`) only has access to one zone (e.g. `mlorente.dev`) but the new subdomain belongs to a different zone (`kubelab.live`).

### Solution

1. Go to Cloudflare dashboard → My Profile → API Tokens
2. Edit the token → Zone Resources → add the missing zone
3. Token value stays the same, only permissions change
4. Restart Traefik: `docker restart traefik`

### Verification

```bash
# Test token access to zone
CF_TOKEN=$(docker inspect traefik --format '{{range .Config.Env}}{{println .}}{{end}}' | grep CF_DNS_API_TOKEN | cut -d= -f2)
curl -s -H "Authorization: Bearer $CF_TOKEN" "https://api.cloudflare.com/client/v4/zones?name=kubelab.live" | python3 -m json.tools | head -5
# Should show "count": 1
```

## ACME Storage Path Mismatch — Non-existent Certificate Resolver

### Problem

All routers show `Router uses a non-existent certificate resolver` in Traefik logs.

### Root Cause

The `storage` path in `traefik.yml` doesn't match the Docker volume mount. Example:
- Config says: `storage: "/etc/traefik/acme/acme.json"`
- Mount is: `-v /opt/traefik/certs/acme.json:/letsencrypt/acme.json`
- Traefik can't find the ACME file → resolver never initializes

### Solution

```bash
# Check what Traefik expects
grep storage /opt/traefik/traefik.yml

# Check what's actually mounted
docker inspect traefik --format '{{json .Mounts}}' | python3 -m json.tools | grep -A2 acme

# Fix: make config match mount
sed -i 's|/etc/traefik/acme/acme.json|/letsencrypt/acme.json|' /opt/traefik/traefik.yml
docker restart traefik
```

### Prevention

- **Never overwrite VPS traefik.yml with toolkit-generated version** — paths differ (VPS: `/letsencrypt/`, toolkit: `/etc/traefik/acme/`)
- See [headscale-setup](../runbooks/headscale-setup.md) "VPS vs Repo Differences" table
