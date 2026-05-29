---
id: "kubelab-troubleshooting-security-authentication"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Security & Authentication Issues

Problems related to authentication, certificates, tokens, and credential management in KubeLab.

## Authentication Failures

### Problem

Cannot login to KubeLab services (Traefik-protected endpoints, API, dashboards).

### Diagnostic Steps

```bash
# Check auth middleware
cat edge/traefik/templates/middlewares.template.yml | grep auth

# Verify credentials
toolkit credentials generate username password
echo -n 'username:password' | base64

# Test auth header
curl -H "Authorization: Basic $(echo -n 'user:pass' | base64)" https://service.kubelab.live
```

### Solution

```bash
# Reset admin credentials
toolkit credentials generate admin newpassword

# Update .htpasswd file
docker exec traefik cat /etc/traefik/.htpasswd

# Disable auth temporarily for debugging
# Comment out auth middleware in Traefik config

# Check token expiration
jwt decode $TOKEN
```

### Prevention

- Store all credentials in Vaultwarden
- Use strong, generated passwords via `toolkit credentials generate`
- Monitor failed authentication attempts in logs

## Certificate Issues

See [ssl-certificates](ssl-certificates.md) for comprehensive SSL/TLS troubleshooting.

### Quick Reference

```bash
# Check certificate validity
openssl s_client -connect api.kubelab.live:443 -servername api.kubelab.live

# View certificate count
docker exec traefik cat /letsencrypt/acme.json | jq '.Certificates | length'

# Force renewal
rm edge/traefik/data/acme.json
chmod 600 edge/traefik/data/acme.json
toolkit edge restart traefik
```

## Token/Secret Problems

### Problem

API tokens are invalid, expired, or rejected.

### Diagnostic Steps

```bash
# Check token format
echo $API_TOKEN | cut -d. -f2 | base64 -d | jq

# Verify secret key
docker exec api-container env | grep SECRET

# Test token generation
curl -X POST https://api.kubelab.live/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password"}'
```

### Solution

```bash
# Regenerate secrets
toolkit credentials generate api-secret

# Update GitHub secrets
toolkit credentials setup-gh-secrets

# Rotate keys in production
# 1. Generate new secret
# 2. Deploy with both old and new
# 3. Wait for token refresh
# 4. Remove old secret

# Validate secret strength
echo $SECRET | wc -c   # Should be >= 32 characters
```

### Prevention

- Rotate secrets on a regular schedule
- Use `toolkit credentials` for all secret generation
- Never commit secrets to version control
- Monitor token usage patterns for anomalies

## Double Login Screen — Services with Own Auth Behind Authelia

### Root Cause

Services that have mandatory own-authentication (portainer, gitea, n8n) placed behind Authelia ForwardAuth produce two sequential login prompts. The Authelia challenge appears first; upon success the user hits the service's own login page. This is not SSO — it is double auth.

### Solution

Two patterns depending on the service:

**Pattern A — Bypass ForwardAuth (infra/dev tools)**

Remove the Authelia middleware from the IngressRoute. Rely on the service's own auth and VPN access control (Tailscale) for network perimeter security.

```yaml
# IngressRoute: omit the authelia middleware for portainer/gitea
routes:
  - match: Host(`portainer.staging.kubelab.live`)
    kind: Rule
    services:
      - name: portainer
        port: 9000
    # No middlewares: [] — Authelia middleware NOT applied
```

**Pattern B — Native OIDC/OAuth2 integration (SSO)**

Configure the service as an OIDC client against Authelia. Single login via Authelia, no service-level login. Supported by minio, grafana.

```yaml
# Authelia: add OIDC client definition for minio
identity_providers:
  oidc:
    clients:
      - id: minio
        secret: $MINIO_OIDC_SECRET
        authorization_policy: one_factor
        redirect_uris:
          - https://minio.staging.kubelab.live/oauth_callback
```

### Decision Matrix

| Service | Auth Strategy | Reason |
| --- | --- | --- |
| portainer | Bypass Authelia | Docker Compose only; own mandatory auth |
| gitea | Bypass Authelia | Own auth; OAuth2 from Authelia in staging/prod |
| n8n | Bypass Authelia | Own user management; no OIDC support |
| minio | OIDC via Authelia | Native OIDC support; SSO preferred |
| grafana | OIDC via Authelia | Native OIDC support; SSO preferred |
| api/web/blog | Authelia ForwardAuth | No own auth; public apps need protection |

### Prevention

Before wiring a service to Authelia ForwardAuth, check: does it have native OIDC? Yes → configure SSO. No → bypass Authelia and rely on VPN perimeter.

---

## Password Resets

### Problem

Locked out of one or more KubeLab services.

### Solution

```bash
# Grafana
docker exec grafana grafana-cli admin reset-admin-password newpass

# Portainer (within 5 min of first start)
curl -X POST http://localhost:9000/api/users/admin/init \
  -H "Content-Type: application/json" \
  -d '{"Username":"admin","Password":"newpassword"}'

# Vaultwarden (disable admin token)
docker exec vaultwarden sed -i 's/"admin_token":.*/"admin_token": null,/' /data/config.json

# N8N (reset via database)
docker exec n8n-db psql -U n8n -c "UPDATE user SET password='hashed_password' WHERE email='admin@kubelab.live';"
```

### Prevention

- Store all service passwords in Vaultwarden
- Document password reset procedures for each service
- Use SSO/OIDC where supported to reduce password sprawl
