# E2E Test Suite

End-to-end tests for all KubeLab infrastructure services. Runs against dev, staging, or production environments.

## Architecture

The suite follows the **Open-Closed Principle**: add a new service to `expectations.py` and all parametrized tests automatically include it. No test file changes needed.

```
tests/e2e/
├── conftest.py              # Fixtures: httpx clients, service discovery, auth
├── expectations.py          # Service registry (THE file to edit for new services)
├── test_health.py           # Health endpoint + reachability (parametrized)
├── test_content.py          # Content-type, body, API endpoints, JSON keys
├── test_auth_flow.py        # Authelia health, unauthenticated rejection, authenticated access
├── test_tls_routing.py      # TLS cert validity, HTTPS redirect, unknown host routing
├── test_api_validation.py   # API input validation (400 on bad input)
├── test_security_headers.py # Traefik security headers (X-Frame-Options, HSTS, etc.)
├── test_error_pages.py      # Custom errors service 404 page validation
├── test_observability.py    # Grafana API, Loki readiness
├── test_crowdsec.py         # CrowdSec bouncer pass-through and health
└── README.md
```

## Running

```bash
# Default: dev environment
make test-e2e

# Specific environment
make test-e2e ENV=staging
make test-e2e ENV=prod
```

## Prerequisites

| Environment | Requirements |
|-------------|-------------|
| dev | Docker Compose stack running, `/etc/hosts` configured |
| staging | Tailscale VPN connected, staging cluster running |
| prod | Tailscale VPN connected, production services running |

### Testuser Setup (for authenticated tests)

1. Add `testuser` to `infra/config/values/common.yaml` under `apps.services.security.authelia.users`
2. Generate Argon2 hash, store in SOPS at `apps.services.security.authelia.users_testuser_password_hash`
3. Store plaintext password in SOPS at `apps.testing.authelia_test_password`
4. Run `toolkit config generate --env dev && docker restart authelia`

Alternatively, set environment variables: `E2E_AUTH_USER` and `E2E_AUTH_PASSWORD`.

## Skip Logic

Tests auto-skip when:
- **Environment unreachable**: DNS or TCP connectivity check fails
- **Service not in config**: Service defined in expectations but absent from environment config
- **`skip_in_envs`**: Service explicitly skipped in certain environments (e.g., `headscale` in dev)
- **No auth session**: Authenticated tests skip if testuser is not provisioned
- **No VPN**: Tests requiring staging/prod access skip if Tailscale is not connected

## Fixture Chain

```
env (CLI --env option)
 └─ e2e_config (merged YAML config)
     └─ services (ServiceHealthConfig list)
         ├─ services_by_name (dict lookup)
         └─ services_by_category (grouped)
 └─ http_client (no redirects, TLS aware)
 └─ http_client_follow (follows redirects)
 └─ authelia_test_credentials (env vars or SOPS)
     └─ authenticated_client (Authelia session cookie)
```

## Adding a New Service

1. Add an entry to `EXPECTATIONS` in `expectations.py`
2. Run `make test-e2e` to verify the name matches the config key
3. All parametrized tests will automatically include the new service
