---
id: "kubelab-troubleshooting-environment-configuration"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Environment & Configuration Issues

Problems related to environment variables, configuration files, and template processing in KubeLab.

## Missing Environment Variables

### Problem

Container fails to start due to missing required environment variables.

### Diagnostic Steps

```bash
# Check required variables
grep -r "required" apps/api/src/pkg/config/

# Verify env file exists
ls -la infra/compose/apps/api/.env.dev

# Compare with example
diff infra/compose/apps/api/.env.dev.example infra/compose/apps/api/.env.dev

# Check container environment
docker exec container-name env | sort
```

### Solution

```bash
# Copy from example
cp infra/compose/apps/api/.env.dev.example infra/compose/apps/api/.env.dev

# Validate environment
make env-validate

# Generate missing values
toolkit credentials generate db-password
toolkit credentials generate jwt-secret

# Source from .env file
set -a; source infra/compose/apps/api/.env.dev; set +a
```

### Prevention

- Keep `.env.example` files up to date with all required variables
- Run `make env-validate` before starting services
- Document new environment variables when adding features

## Invalid Configuration Values

### Problem

Services fail to start due to malformed configuration values.

### Diagnostic Steps

```bash
# Validate compose files
docker compose -f infra/compose/apps/api/docker-compose.dev.yml config

# Check YAML syntax
yamllint -c infra/config/yamllint.yml infra/compose/apps/api/

# Verify template expansion
ENVIRONMENT=dev toolkit config generate
cat edge/traefik/config/dynamic/app-api.yml
```

### Solution

```bash
# Fix YAML indentation (use spaces, not tabs)

# Validate URLs
echo $DATABASE_URL | grep -E '^postgres://.+:.+@.+:.+/.+$'

# Check port conflicts
netstat -tulpn | grep :8080

# Regenerate configs
rm -rf edge/traefik/config/dynamic/
ENVIRONMENT=dev toolkit config generate
```

### Prevention

- Use `yamllint` in CI to catch syntax errors
- Validate environment variables with schema (e.g., Pydantic in toolkit)
- Test configuration generation in CI

## Template Processing Errors

### Problem

Template variables (`${VAR}`) not replaced in generated configuration files.

### Diagnostic Steps

```bash
# Check template syntax
grep -r '\${.*}' edge/traefik/templates/

# Verify environment is set
echo $ENVIRONMENT

# Test template manually
envsubst < edge/traefik/templates/app-api.template.yml
```

### Solution

```bash
# Use toolkit for generation (handles env loading)
ENVIRONMENT=dev toolkit config generate

# Check .env file is loaded
source infra/config/env/.env.dev
env | grep TRAEFIK

# Verify template paths in constants
cat toolkit/config/constants.py | grep TEMPLATE

# Debug template processor
poetry run python -c "from toolkit.features.template_processor import TemplateProcessor; print(TemplateProcessor.process_template('template.yml'))"
```

### Prevention

- Always use `toolkit config generate` instead of manual `envsubst`
- Validate generated configs are free of unexpanded variables
- Add template expansion tests to CI
