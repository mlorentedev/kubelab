# Contributing to mlorente.dev

Thank you for your interest in contributing! This document provides guidelines for contributing to the mlorente.dev platform.

## Quick Start

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR-USERNAME/mlorente.dev
   cd mlorente.dev
   ```

3. Setup development environment:
   ```bash
   # Install Poetry (if not already installed)
   curl -sSL https://install.python-poetry.org | python3 -

   # Install toolkit dependencies
   poetry install

   # Install pre-commit hooks (IMPORTANT)
   poetry run pre-commit install

   # Setup local environment files
   poetry run toolkit tools env-init dev
   ```

4. Start development stack:
   ```bash
   # Start core services
   make dev

   # Or start specific apps
   poetry run toolkit services up web
   poetry run toolkit services up api
   ```

## Project Structure

```
mlorente.dev/
├── apps/                    # Source code for custom applications
├── edge/                    # Network edge services (Traefik, Nginx, DNS)
├── infra/
│   ├── stacks/              # Docker Compose deployments
│   │   ├── apps/            # App deployment configs
│   │   ├── services/        # Third-party service configs
│   │   └── edge/            # Edge service stacks
│   ├── ansible/             # Server provisioning
│   ├── terraform/           # DNS management
│   └── config/              # Global configuration
└── toolkit/                 # Python CLI tool
```

## Development Workflow

### Making Changes to Applications

1. Edit source code in `apps/{app-name}/`
2. Copy environment files for Docker build:
   ```bash
   # Copy .env files to app directory for Dockerfile access
   cp infra/stacks/apps/web/.env.dev apps/web/.env.dev
   ```

3. Test locally:
   ```bash
   poetry run toolkit services build web
   poetry run toolkit services up web
   poetry run toolkit services logs web
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
   make format   # Format with black + ruff
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

```
feature/short-description    # New features
fix/bug-description          # Bug fixes
docs/what-changed            # Documentation updates
refactor/component-name      # Code restructuring
```

### Code Style

Go (API):
- Use `gofmt` and `golint`
- Follow [Effective Go](https://golang.org/doc/effective_go.html)
- Add tests for new features

Python (Toolkit):
- Use `black` for formatting
- Use `ruff` for linting
- Use `mypy` for type checking (strict mode)
- Follow PEP 8

JavaScript/TypeScript (Web/Blog):
- Use Prettier and ESLint
- Add TypeScript types
- Follow existing component patterns

Markdown (Documentation):
- Use clear, concise language
- Include code examples
- Test all command examples

## Testing

```bash
# Validate environment files
poetry run toolkit tools env-validate

# Test app builds
poetry run toolkit services build web
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
- [ ] Environment files updated (if adding new variables)
- [ ] `.env.*.example` files generated:
      ```bash
      poetry run toolkit tools env-examples dev
      ```
- [ ] Documentation updated (if changing functionality)
- [ ] Commit messages follow Conventional Commits format
- [ ] No secrets committed (pre-commit hooks verify this)

### PR Description Template

```markdown
## Summary
Brief description of changes

## Changes Made
- List of specific changes
- Another change

## Testing
How to test these changes:
1. Step one
2. Step two

## Breaking Changes
List any breaking changes (if applicable)

## Screenshots
Include screenshots for UI changes
```

## Environment Variables

When adding new environment variables:

1. Add to `.env.{environment}` files in:
   - `infra/stacks/apps/{app}/` (for apps)
   - `infra/stacks/services/{category}/{service}/` (for services)
   - `infra/config/env/` (for global variables)

2. Generate sanitized examples:
   ```bash
   poetry run toolkit tools env-examples dev
   poetry run toolkit tools env-examples staging
   poetry run toolkit tools env-examples prod
   ```

3. Update documentation:
   - App/service README.md

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

1. Changes merged to `master` branch
2. CI/CD automatically:
   - Detects changed apps
   - Calculates version (semantic versioning)
   - Builds Docker images
   - Pushes to Docker Hub
   - Creates git tags

3. Manual deployment:
   ```bash
   # Deploy to staging
   make deploy-staging

   # Deploy to production
   make deploy-prod
   ```

4. Create GitHub release for major versions

## Toolkit CLI

The `toolkit` CLI is your primary development tool:

```bash
# Apps and services management
poetry run toolkit services up web
poetry run toolkit services logs api --follow
poetry run toolkit services down blog
poetry run toolkit services list
poetry run toolkit services up grafana
poetry run toolkit services logs portainer

# Configuration generation
poetry run toolkit config generate traefik dev

# Environment tools
poetry run toolkit tools env-validate
poetry run toolkit tools env-examples dev

# Deployment
ENVIRONMENT=staging poetry run toolkit deployment deploy
```

## Questions?

- Issues: Create a [GitHub issue](https://github.com/mlorente/mlorente.dev/issues)
- Discussions: Start a [GitHub discussion](https://github.com/mlorente/mlorente.dev/discussions)

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on the code, not the person
- Help others learn and grow

Thank you for contributing to mlorente.dev!
