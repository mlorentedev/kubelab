# =============================================================================
# Makefile – Minimal bootstrap and top-level orchestration
# =============================================================================
# This Makefile provides ONLY:
#   1. Bootstrap (setup Python, Poetry, toolkit)
#   2. Help/discovery
#   3. Top-level convenience aliases
#
# For all other operations, use toolkit directly:
#   toolkit services up web
#   toolkit services logs api
#   toolkit services up grafana
#   toolkit deployment deploy
# =============================================================================

SHELL := /bin/bash
.SHELLFLAGS := -c -o pipefail

POETRY ?= poetry
TOOLKIT := $(POETRY) run toolkit
PYTHON_VERSION ?= 3.12

.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------
.PHONY: help
help:
	@echo "=== KubeLab ==="
	@echo ""
	@echo "Bootstrap:"
	@echo "  make setup              Install Poetry, dependencies, and toolkit"
	@echo "  make setup-local-dns    Add local DNS entries to /etc/hosts"
	@echo ""
	@echo "Development:"
	@echo "  make up-dev             Start all dev services"
	@echo "  make down-dev           Stop all dev services"
	@echo "  make restart-dev        Restart all dev services"
	@echo "  make build-dev          Build all app images (no cache)"
	@echo "  make config-generate    Generate config files for dev"
	@echo "  make credentials-generate  Generate credentials for dev"
	@echo "  make secrets            Edit SOPS-encrypted dev secrets"
	@echo "  make dev-full-reset     Full teardown + rebuild + restart"
	@echo ""
	@echo "Quality:"
	@echo "  make check              Run all checks (lint + type + test)"
	@echo "  make lint               Ruff linting (check only)"
	@echo "  make format             Ruff formatting (auto-fix)"
	@echo "  make type               Mypy type checking"
	@echo "  make test               Run pytest suite"
	@echo "  make validate           Validate toolkit config"
	@echo "  make smoke-test         Health check running services"
	@echo ""
	@echo "Deployment:"
	@echo "  make deploy-staging     Deploy to staging environment"
	@echo "  make deploy-prod        Deploy to production environment"
	@echo ""
	@echo "Toolkit CLI (use directly for most operations):"
	@echo "  toolkit services up web          Start web app"
	@echo "  toolkit services logs api        View API logs"
	@echo "  toolkit --help                   Show all commands"
	@echo ""

# -----------------------------------------------------------------------------
# Bootstrap
# -----------------------------------------------------------------------------
.PHONY: setup
setup: setup-python setup-poetry setup-dependencies setup-sops setup-certs
	@echo "✓ Setup complete. Run 'toolkit --help' to see available commands"

.PHONY: setup-python
setup-python:
	@if ! command -v python3 >/dev/null 2>&1; then \
		echo "Error: Python 3 is required"; \
		exit 1; \
	fi
	@python3 -m pip install --upgrade pip >/dev/null 2>&1

.PHONY: setup-poetry
setup-poetry:
	@python3 -m pip install --upgrade poetry >/dev/null 2>&1
	@$(POETRY) config virtualenvs.create true
	@$(POETRY) config virtualenvs.in-project true

.PHONY: setup-dependencies
setup-dependencies:
	@$(POETRY) install

.PHONY: setup-sops
setup-sops:
	@if ! command -v sops >/dev/null 2>&1; then \
		echo "Error: sops is required for managing encrypted secrets"; \
		exit 1; \
	fi

.PHONY: setup-certs
setup-certs:
	@echo "Setting up TLS certificates for local development..."
	@$(TOOLKIT) tools certs install-mkcert || true
	@$(TOOLKIT) tools certs generate --env dev
	@mkcert -install >/dev/null 2>&1 || true
	@echo "✓ TLS certificates configured"

.PHONY: setup-local-dns
setup-local-dns:
	@echo "Setting up local DNS entries in /etc/hosts..."
	@if grep -q "kubelab.test" /etc/hosts 2>/dev/null && grep -q "mlorente.test" /etc/hosts 2>/dev/null; then \
		echo "✓ DNS entries already configured"; \
	else \
		echo "Adding local development DNS entries..."; \
		echo "" | sudo tee -a /etc/hosts > /dev/null; \
		echo "# KubeLab local development" | sudo tee -a /etc/hosts > /dev/null; \
		echo "127.0.0.1 mlorente.test" | sudo tee -a /etc/hosts > /dev/null; \
		echo "127.0.0.1 traefik.kubelab.test api.kubelab.test blog.kubelab.test" | sudo tee -a /etc/hosts > /dev/null; \
		echo "127.0.0.1 auth.kubelab.test gitea.kubelab.test grafana.kubelab.test loki.kubelab.test" | sudo tee -a /etc/hosts > /dev/null; \
		echo "127.0.0.1 portainer.kubelab.test status.kubelab.test minio.kubelab.test" | sudo tee -a /etc/hosts > /dev/null; \
		echo "127.0.0.1 console.minio.kubelab.test" | sudo tee -a /etc/hosts > /dev/null; \
		echo "✓ DNS entries added to /etc/hosts"; \
	fi

# -----------------------------------------------------------------------------
# Development Shortcuts
# -----------------------------------------------------------------------------

.PHONE: credentials-generate
credentials-generate:
	@$(TOOLKIT) credentials generate --env dev
	@echo "✓ Credentials generated"

.PHONY: config-generate
config-generate:
	@$(TOOLKIT) config generate --env dev
	@echo "✓ Configuration files generated"

.PHONY: build-dev
build-dev:
	@$(TOOLKIT) services build blog --env dev --no-cache
	@$(TOOLKIT) services build api --env dev --no-cache
	@$(TOOLKIT) services build web --env dev --no-cache
	@echo "✓ Development services built"

.PHONY: up-dev
up-dev:
	@$(TOOLKIT) services up \
		blog api web nginx portainer uptime loki grafana authelia crowdsec minio github-runner traefik \
		--env dev
	@echo "✓ Development environment is up"

.PHONY: down-dev
down-dev:
	@echo "--- Bringing down ALL development services and removing volumes ---"
	@$(TOOLKIT) services down \
		blog api web nginx portainer uptime loki grafana authelia crowdsec minio github-runner traefik \
		--env dev -v || true
	@echo "✓ All development services are down and volumes removed"

.PHONY: dev-full-clean
dev-full-clean: down-dev
	@echo "--- Ensuring all Docker containers and volumes are removed ---"
	@docker volume prune -f || true
	@docker container prune -f || true
	@echo "✓ Docker environment cleaned"

.PHONY: dev-full-reset
dev-full-reset: dev-full-clean credentials-generate
	@echo "============================================================"
	@echo "--- MANUAL STEP REQUIRED ---"
	@echo "After 'make credentials-generate' finished (output above this message),"
	@echo "you MUST copy the generated secrets from the console output"
	@echo "into your infra/config/secrets/dev.enc.yaml file."
	@echo "  -> To do this, run: 'sops edit infra/config/secrets/dev.enc.yaml'"
	@echo "  -> Paste the relevant sections from the output above."
	@echo "  -> Save and close the editor (sops will encrypt it)."
	@echo "Press ENTER to continue AFTER you have updated your secrets..."
	@read -p "" # Pauses execution until user presses Enter
	@$(TOOLKIT) config generate --env dev # Regenerate config with updated secrets
	@echo "--- Starting all services ---"
	@$(TOOLKIT) services up crowdsec authelia traefik portainer uptime loki grafana api web blog minio github-runner --env dev
	@echo "✓ Development environment fully reset and services are up."
	@echo "============================================================"

.PHONY: restart-dev
restart-dev: down-dev up-dev
	@echo "✓ Development environment restarted"

.PHONY: secrets
secrets:
	@EDITOR=nano sops ./infra/config/secrets/dev.enc.yaml
	@echo "✓ Secrets setup complete"


# -----------------------------------------------------------------------------
# Deployment Shortcuts
# -----------------------------------------------------------------------------
.PHONY: deploy-staging
deploy-staging:
	@ENVIRONMENT=staging $(TOOLKIT) deployment deploy --env staging

.PHONY: deploy-prod
deploy-prod:
	@ENVIRONMENT=prod $(TOOLKIT) deployment deploy --env prod

# -----------------------------------------------------------------------------
# Validation & Testing
# -----------------------------------------------------------------------------
.PHONY: smoke-test
smoke-test:
	@$(TOOLKIT) services health --env dev

.PHONY: validate
validate:
	@$(TOOLKIT) config validate

.PHONY: test
test:
	@$(POETRY) run pytest

.PHONY: format
format:
	@$(POETRY) run ruff check --select I --fix toolkit
	@$(POETRY) run ruff format toolkit

.PHONY: lint
lint:
	@$(POETRY) run ruff check toolkit
	@$(POETRY) run ruff format --check toolkit

.PHONY: type
type:
	@$(POETRY) run mypy toolkit

.PHONY: check
check: lint type test
	@echo "✓ All checks passed"
