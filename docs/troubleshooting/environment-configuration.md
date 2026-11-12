---
id: "kubelab-troubleshooting-environment-configuration"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Environment & Configuration Issues

Problems with the values a container receives and with generated configuration in KubeLab.

There are no `.env` files to edit. Every value comes from one SSOT: `infra/config/values/{common,<env>}.yaml` for non-secrets and SOPS (`infra/config/secrets/<env>.enc.yaml`) for secrets. `toolkit services up` merges them, flattens each nested key to an upper-case variable (`apps.platform.api.default_port` becomes `APPS_PLATFORM_API_DEFAULT_PORT`) and passes the result to Docker Compose, which interpolates it into `infra/stacks/**/compose.*.yml`.

## Missing Environment Variables

### Problem

A container fails to start, or starts with an empty value, because a variable its compose file reads is not set.

### Diagnostic Steps

```bash
# Which variable does the compose file read?
grep -n "environment:" -A20 infra/stacks/apps/api/compose.base.yml

# Is the non-secret value declared? (prints one SSOT value, never a secret)
poetry run toolkit config get apps.platform.api.default_port

# Is every catalogued secret present for the environment?
make secrets-audit

# What did the container actually receive?
docker exec <container> env | sort
```

`make secrets-audit` lists a missing key and still exits 0, so read its output.

### Solution

- A non-secret: add it under its nested key in `infra/config/values/common.yaml`, or in `<env>.yaml` when it differs per environment.
- A secret: register it in `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`) and set it with `poetry run toolkit secrets set <key.path> --env <env> --stdin`.
- Restart the service so Compose reads the new value: `poetry run toolkit services restart api`.

### Prevention

- Run `make validate` and `make secrets-audit` after adding a variable.
- Never put a SOPS value in a K8s ConfigMap; it goes in a Secret (see `CLAUDE.md`).

## Invalid Configuration Values

### Problem

A service fails to start because a value is malformed or a compose file does not parse.

### Diagnostic Steps

```bash
# YAML syntax of the stack and the values
pre-commit run yamllint --files infra/stacks/apps/api/*.yml infra/config/values/*.yaml

# The value as the SSOT holds it
poetry run toolkit config get apps.platform.api.site_url

# Port already taken on the host
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

### Solution

Fix the value in `infra/config/values/*.yaml` (spaces, not tabs), then regenerate and restart:

```bash
make config-generate ENV=dev
poetry run toolkit services restart api
```

### Prevention

- The pre-commit hooks run yamllint on every staged YAML file.
- CI runs `make config-check-drift ENV=<env>` for staging and prod.

## Template Processing Errors

### Problem

A generated file (Traefik static or dynamic config, Ansible inventory, Terraform variables) is missing, stale or wrong.

### Diagnostic Steps

```bash
# Templates are Jinja2, rendered by the toolkit; nothing is envsubst-ed
ls edge/traefik/templates/

# Render for one environment and look at the output
make config-generate ENV=dev
ls edge/traefik/generated/dev/

# Does the committed output match what the generator renders?
make config-check-drift ENV=staging
```

### Solution

- Edit the template (`*.j2`) or the SSOT value it reads, never the generated file.
- Regenerate with `make config-generate ENV=<env>` and commit the template, the value and the output together.

### Prevention

- `make config-check-drift ENV=<env>` fails when a committed output differs from what the generator renders.
- `make validate` sanity-checks the generated files.
