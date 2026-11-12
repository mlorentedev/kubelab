---
id: "kubelab-troubleshooting-services-traefik-nginx"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Traefik & Error Pages Troubleshooting

Service-specific troubleshooting for the KubeLab edge layer: the Traefik reverse proxy and the `errors` service that serves the branded error pages.

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
toolkit services restart traefik
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

## Error pages

There is no standalone Nginx tier. The edge is K3s Traefik, and the only Nginx is
the one inside the `errors` service (`edge/errors/`), which serves the branded error
pages. Traefik reaches it through the `error-pages` Middleware in
`infra/k8s/base/edge/errors.yaml` (ADR-072).

### Branded page not shown for a backend failure

#### Problem

A request to a down backend returns Traefik's plain "no available server" or a bare
5xx instead of the branded page.

#### Diagnostic Steps

```bash
# Is the errors workload up?
kubectl --kubeconfig ~/.kube/kubelab-staging-config -n kubelab get deploy,svc errors

# Does this route carry the middleware? Read the route's own middlewares list:
# the string "error-pages" also matches the Middleware object itself.
kubectl --kubeconfig ~/.kube/kubelab-staging-config -n kubelab \
  get ingressroute <route> -o jsonpath='{.spec.routes[*].middlewares[*].name}'

# Offline, for every route in both overlays at once:
poetry run pytest tests/test_error_pages_coverage.py
```

#### Solution

- The middleware intercepts **502, 503 and 504 only**. A 4xx or a 500 is the app's
  own answer and passes through on purpose, with its headers intact (ADR-072).
- A route without `error-pages` must be declared in `edge.errors.coverage.exceptions`
  in `common.yaml`. `tests/test_error_pages_coverage.py` fails on a rule that has
  neither.
- A page that never shows: `tests/test_error_pages_reachable.py` fails on an HTML file
  in `edge/errors/html/errors/` that no Middleware range or nginx `error_page` targets.

#### Prevention

- Run `make test` before merging any IngressRoute change: the two tests above render
  both overlays.
- The `errors` image is promoted like any custom app (`edge.errors.version` in
  `common.yaml`), never hand-pinned.
