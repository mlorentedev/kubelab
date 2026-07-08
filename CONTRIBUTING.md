# Contributing to KubeLab

Thank you for your interest in contributing! This document provides guidelines for contributing to the KubeLab platform.

## Quick Start

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR-USERNAME/kubelab
   cd kubelab
   ```

3. Setup development environment:
   ```bash
   # Install Poetry (if not already installed)
   curl -sSL https://install.python-poetry.org | python3 -

   # Install toolkit dependencies
   poetry install

   # Install pre-commit hooks (IMPORTANT)
   poetry run pre-commit install

   # Bootstrap the dev environment (deps, SOPS, certs, local DNS)
   make setup
   ```

4. Start development stack:
   ```bash
   # Start core services
   make up-dev

   # Or start a specific app
   poetry run toolkit services up api
   ```

## Project Structure

See the canonical project tree in [README.md](README.md#project-structure). Highlights:

```
kubelab/
├── apps/                    # Custom application source (api; wiki = generated docs)
├── edge/                    # Network edge (Traefik config, error pages)
├── infra/
│   ├── k8s/                 # Kubernetes manifests (base + overlays)
│   ├── stacks/              # Docker Compose stacks (dev environment)
│   ├── ansible/             # Server provisioning
│   ├── terraform/           # DNS (Cloudflare) + AWS hub
│   └── config/              # Values YAML (SSOT) + SOPS secrets
└── toolkit/                 # Python CLI tool
```

## Development Workflow

### Making Changes to Applications

1. Edit source code in `apps/{app-name}/`
2. Configuration comes from `infra/config/values/*.yaml` (SSOT) — regenerate derived
   configs with `make config-generate` if you changed values.

3. Test locally:
   ```bash
   poetry run toolkit services build api
   poetry run toolkit services up api
   poetry run toolkit services logs api
   ```

4. Commit changes:
   ```bash
   git add .
   git commit -m "feat: add new feature to web app"
   ```

### Making Changes to Services

1. Navigate to service in `infra/stacks/services/{category}/{service}/`
2. Update configuration (docker-compose, .env files)
3. Test:
   ```bash
   poetry run toolkit services up {service-name}
   ```

### Making Changes to Toolkit

1. Edit Python code in `toolkit/`
2. Follow type safety:
   ```bash
   make type     # Run mypy type checking
   make format   # Format with ruff
   ```

3. Test changes:
   ```bash
   poetry run toolkit --help
   poetry run pytest  # Run tests
   ```

### Pre-commit Hooks

Pre-commit hooks run automatically before each commit to catch issues early:

```bash
# Install hooks (first time only)
poetry run pre-commit install

# Run manually on all files
poetry run pre-commit run --all-files

# Run on specific files
poetry run pre-commit run --files toolkit/cli/services.py
```

**What the hooks check:**
- **Secret detection:** Scans for exposed API keys, tokens, credentials
- **Python quality:** Black formatting, Ruff linting, mypy type checking
- **YAML/JSON validation:** Ensures config files are valid
- **Path consistency:** Prevents old path references (e.g., `infra/compose/edge`)
- **Environment files:** Blocks committing real `.env.dev/staging/prod` files
- **Markdown linting:** Ensures documentation follows standards

If hooks fail, fix the issues and commit again. Some hooks auto-fix issues (like formatting).

## Code Standards

### Commit Messages

Use [Conventional Commits](https://conventionalcommits.org/):

```
feat: add user authentication
fix: resolve database connection issue
docs: update API documentation
style: format Python code with black
refactor: reorganize toolkit structure
test: add unit tests for env manager
chore: update dependencies
```

### Branch Naming

CI accepts these prefixes (enforced by the branch-name check in `ci.yml`):

```
feature/short-description    # New features
fix/bug-description          # Bug fixes
hotfix/bug-description       # Urgent production fixes
chore/what-changed           # Maintenance, docs, refactors
```

### Code Style

Go (API):
- Use `gofmt` and `golint`
- Follow [Effective Go](https://golang.org/doc/effective_go.html)
- Add tests for new features

Python (Toolkit):
- Use `ruff` for formatting and linting
- Use `mypy` for type checking (strict mode)
- Follow PEP 8

Markdown (Documentation):
- Use clear, concise language
- Include code examples
- Test all command examples

## Testing

```bash
# Validate generated configuration
make validate

# Test app builds
poetry run toolkit services build api

# Run Python toolkit tests
poetry run pytest

# Type checking
make type
```

## Pull Request Checklist

Before submitting a PR, ensure:

- [ ] **Pre-commit hooks installed and passing:**
      ```bash
      poetry run pre-commit install
      poetry run pre-commit run --all-files
      ```
- [ ] Code follows style guidelines (run `make format` for Python)
- [ ] All tests pass (`poetry run pytest`)
- [ ] Type checking passes (`make type`)
- [ ] Config values updated in `infra/config/values/` (if adding new variables) and
      drift gate green (`make config-check-drift`)
- [ ] Documentation updated (if changing functionality)
- [ ] Commit messages follow Conventional Commits format
- [ ] No secrets committed (pre-commit hooks verify this)

### PR Description Template

The canonical template lives at [`.github/pull_request_template.md`](.github/pull_request_template.md) and is applied automatically when you open a PR.

## Configuration & Secrets

Configuration is SSOT-driven — never edit `.env` files or generated output directly:

1. Non-secret values go in `infra/config/values/{common,dev,staging,prod}.yaml`.
2. Secrets go through the toolkit (SOPS/age): `poetry run toolkit secrets edit --env <env>`;
   the authoritative registry is `SECRET_CATALOG` in `toolkit/features/secrets_manager.py`.
3. Regenerate derived configs with `make config-generate`; CI enforces the drift gate
   (`make config-check-drift`).

## Docker Guidelines

### Dockerfile Best Practices

- Use multi-stage builds
- Minimize layer count
- Use specific base image tags (avoid `latest`)
- Don't run as root user
- Clean up package caches
- Copy `.env` files when needed for build

Example:
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app

# Copy env file for build-time variables
COPY .env.dev .env

COPY package*.json ./
RUN npm ci --only=production

FROM node:20-alpine
RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001
WORKDIR /app
COPY --from=builder --chown=nodejs:nodejs /app .
USER nodejs
EXPOSE 3000
CMD ["node", "server.js"]
```

## Documentation

When changing functionality:

- Update relevant README.md files
- Test all documentation steps

## Release Process

1. PRs squash-merge to `master` (trunk-based; no `develop` branch).
2. CI/CD automatically:
   - Detects changed apps (`api`, `errors`) and builds `sha-<short>` images
   - `staging-deploy.yml` promotes the sha to staging via a `chore(staging): deploy` PR
   - release-please (`release.yml`) cuts per-app semver tags (`api-vX.Y.Z`) and re-tags
     the staging sha digest (build-once, ADR-056)
3. Production promotion is a manual gate: the `promote-prod.yml` workflow; Argo CD
   syncs the prod spoke (`selfHeal: true`).

See [`docs/runbooks/gitops-delivery-promotion.md`](docs/runbooks/gitops-delivery-promotion.md) — the canonical delivery/rollback reference.

## Toolkit CLI

The `toolkit` CLI is your primary development tool:

```bash
# Apps and services management
poetry run toolkit services up api
poetry run toolkit services logs api --follow
poetry run toolkit services list
poetry run toolkit services up grafana

# Configuration generation
poetry run toolkit config generate traefik --env dev

# Secrets (SOPS/age — the only supported path)
poetry run toolkit secrets show
poetry run toolkit secrets audit

# Deployment
poetry run toolkit deployment deploy --env staging
```

## Questions?

- Issues: Create a [GitHub issue](https://github.com/mlorentedev/kubelab/issues)
- Discussions: Start a [GitHub discussion](https://github.com/mlorentedev/kubelab/discussions)

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on the code, not the person
- Help others learn and grow

Thank you for contributing to KubeLab!
