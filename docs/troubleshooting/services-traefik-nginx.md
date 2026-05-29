---
id: "kubelab-troubleshooting-services-traefik-nginx"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Traefik & Nginx Troubleshooting

Service-specific troubleshooting for the KubeLab edge layer: Traefik reverse proxy and Nginx caching/static serving.

## Traefik

### Dashboard Not Accessible

#### Problem

Cannot access the Traefik management dashboard.

#### Diagnostic Steps

```bash
# Check Traefik is running
docker ps | grep traefik

# Verify dashboard configuration
cat edge/traefik/templates/traefik.http.template.yml | grep dashboard

# Check authentication
toolkit credentials generate traefik-user password
```

#### Solution

```bash
# Access dashboard
open http://localhost:8080   # Dev
open https://traefik.kubelab.live   # Prod
```

#### Prevention

- Monitor Traefik container health
- Include dashboard access in post-deploy verification

### Certificate Issues

See [ssl-certificates](ssl-certificates.md) for comprehensive SSL/TLS troubleshooting.

#### Quick Fix

```bash
# Check acme.json permissions
ls -la edge/traefik/data/acme.json
chmod 600 edge/traefik/data/acme.json

# View certificate status
docker exec traefik cat /letsencrypt/acme.json | jq '.Certificates'

# Force certificate renewal
rm edge/traefik/data/acme.json
toolkit edge restart traefik
```

### Load Balancing Problems

#### Problem

Uneven traffic distribution or sticky session failures.

#### Diagnostic Steps

```bash
# Check service health in Traefik
curl http://localhost:8080/api/http/services | jq

# Verify sticky sessions
grep -r "sticky" edge/traefik/templates/

# Test load distribution
for i in {1..10}; do curl -s https://api.kubelab.live/health; done
```

#### Solution

- Review Traefik service configuration for correct load balancing mode
- Verify all backend instances are healthy
- Check sticky session cookie configuration if session affinity is required

## Nginx

### Cache Not Working

#### Problem

Nginx proxy cache is not serving cached content.

#### Diagnostic Steps

```bash
# Check cache directory
docker exec nginx ls -la /var/cache/nginx

# Verify cache configuration
docker exec nginx cat /etc/nginx/nginx.conf | grep proxy_cache
```

#### Solution

```bash
# Clear cache
docker exec nginx rm -rf /var/cache/nginx/
toolkit edge restart nginx
```

#### Prevention

- Monitor cache hit ratio in access logs
- Set appropriate cache TTLs for different content types

### Custom Error Pages Not Showing

#### Problem

Default Nginx error pages appear instead of custom branded pages.

#### Diagnostic Steps

```bash
# Verify error page files exist
docker exec nginx ls -la /usr/share/nginx/errors/

# Check error page configuration
docker exec nginx cat /etc/nginx/nginx.conf | grep error_page

# Test error pages
curl -I https://kubelab.live/nonexistent   # Should return custom 404
```

#### Solution

- Verify error page files are mounted in the container
- Check Nginx configuration syntax: `docker exec nginx nginx -t`
- Ensure `error_page` directives reference the correct file paths

#### Prevention

- Include error page tests in the deployment verification suite
- Mount error pages via Docker volumes for easy updates
