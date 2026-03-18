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
	@echo "  make setup              Install Poetry, dependencies, toolkit, and Ansible collections"
	@echo "  make setup-local-dns    Add local DNS entries to /etc/hosts"
	@echo ""
	@echo "Development:"
	@echo "  make up-dev             Start all dev services"
	@echo "  make down-dev           Stop all dev services"
	@echo "  make restart-dev        Restart all dev services"
	@echo "  make build-dev          Build all app images (no cache)"
	@echo "  make config-generate    Generate config files for dev"
	@echo "  make credentials-generate  Generate credentials for dev"
	@echo "  make regen-certs        Regenerate dev TLS certs and reinstall browser CA"
	@echo "  make secrets ENV=x      Edit SOPS-encrypted secrets (default: dev)"
	@echo "  make secrets-init ENV=x Generate machine secrets for an env"
	@echo "  make secrets-jwks ENV=x Generate OIDC JWKS RSA key for an env"
	@echo "  make secrets-hash ENV=x Hash all OIDC client secrets"
	@echo "  make secrets-audit      Audit secrets across all environments"
	@echo "  make dev-full-reset     Full teardown + rebuild + restart"
	@echo "  make dev-app APP=x      Start Astro app dev server (site, astro-site)"
	@echo "  make build-app APP=x    Build Astro app (static output)"
	@echo ""
	@echo "Infrastructure (Ansible):"
	@echo "  make provision NODE=x ENV=y  Provision a node (NODE=ace1|ace2|rpi4)"
	@echo "  make deploy TARGET=x ENV=y  Deploy services (TARGET=vps|dns|k3s)"
	@echo "  make backup ENV=x           Backup VPS volumes (default: prod)"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make deploy-k8s ENV=x   Deploy ALL K8s workloads (Helm + legacy kustomize)"
	@echo "  make helm-deploy ENV=x  Deploy via Helm only"
	@echo "  make helm-template ENV=x Render Helm templates (dry-run)"
	@echo ""
	@echo "Quality:"
	@echo "  make check              Run all checks (lint + type + test)"
	@echo "  make lint               Ruff linting (check only)"
	@echo "  make format             Ruff formatting (auto-fix)"
	@echo "  make type               Mypy type checking"
	@echo "  make test               Run pytest suite (unit/integration only)"
	@echo "  make test-e2e ENV=x     Run e2e tests (ENV=dev|staging|prod)"
	@echo "  make test-infra ENV=x   Run infra tests (ENV=staging|prod, requires VPN)"
	@echo "  make validate           Validate toolkit config"
	@echo "  make smoke-test         Health check running services"
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
setup: setup-python setup-poetry setup-dependencies setup-sops setup-certs setup-ansible
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

.PHONY: setup-ansible
setup-ansible:
	@if command -v ansible-galaxy >/dev/null 2>&1; then \
		echo "Installing Ansible Galaxy collections..."; \
		ansible-galaxy collection install -r infra/ansible/requirements.yml >/dev/null 2>&1; \
		echo "✓ Ansible collections installed"; \
	else \
		echo "⚠ ansible-galaxy not found — skipping Ansible setup (install with: pip install ansible)"; \
	fi

.PHONY: regen-certs
regen-certs:
	@echo "Regenerating dev TLS certificates..."
	@$(TOOLKIT) tools certs generate --env dev
	@mkcert -install >/dev/null 2>&1 || true
	@echo "✓ Certificates regenerated. Restart Traefik and your browser."
	@$(TOOLKIT) services restart traefik --env dev || true

# All dev domains — update this list when adding new services
DEV_DOMAINS := mlorente.test \
	traefik.kubelab.test api.kubelab.test blog.kubelab.test \
	auth.kubelab.test grafana.kubelab.test loki.kubelab.test \
	portainer.kubelab.test gitea.kubelab.test n8n.kubelab.test \
	status.kubelab.test minio.kubelab.test console.minio.kubelab.test \
	crowdsec.kubelab.test errors.kubelab.test

.PHONY: setup-local-dns
setup-local-dns:
	@echo "Setting up local DNS entries in /etc/hosts..."
	@added=0; \
	for domain in $(DEV_DOMAINS); do \
		if ! grep -q "$$domain" /etc/hosts 2>/dev/null; then \
			echo "127.0.0.1 $$domain" | sudo tee -a /etc/hosts > /dev/null; \
			echo "  + $$domain"; \
			added=$$((added+1)); \
		fi; \
	done; \
	if [ $$added -eq 0 ]; then \
		echo "✓ All DNS entries already configured"; \
	else \
		echo "✓ Added $$added DNS entries to /etc/hosts"; \
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
	@$(TOOLKIT) services build api --env dev --no-cache
	@$(TOOLKIT) services build web --env dev --no-cache
	@$(TOOLKIT) services build errors --env dev --no-cache
	@echo "✓ Development services built"

.PHONY: up-dev
up-dev:
	@$(TOOLKIT) services up \
		api web errors portainer gitea n8n uptime loki grafana authelia crowdsec minio github-runner traefik \
		--env dev
	@echo "✓ Development environment is up"

.PHONY: down-dev
down-dev:
	@echo "--- Bringing down ALL development services and removing volumes ---"
	@$(TOOLKIT) services down \
		api web errors portainer gitea n8n uptime loki grafana authelia crowdsec minio github-runner traefik \
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
	@$(TOOLKIT) services up crowdsec authelia traefik portainer gitea n8n uptime loki grafana api web errors minio github-runner --env dev
	@echo "✓ Development environment fully reset and services are up."
	@echo ""
	@echo "--- Post-start manual steps ---"
	@echo "  Portainer : set admin password at https://portainer.kubelab.test"
	@echo "  Gitea     : docker exec --user git gitea gitea admin user create --admin --username admin --password <pass> --email <email> --must-change-password=false"
	@echo "  n8n       : create owner account at https://n8n.kubelab.test"
	@echo "  MinIO     : login at https://console.minio.kubelab.test with root creds from SOPS"
	@echo "============================================================"

.PHONY: restart-dev
restart-dev: down-dev up-dev
	@echo "✓ Development environment restarted"

# Astro apps (standalone dev, no Docker)
# Usage: make dev-app APP=site | make build-app APP=site
APP ?= site
.PHONY: dev-app
dev-app:
	@cd apps/web/$(APP) && npm run dev

.PHONY: build-app
build-app:
	@cd apps/web/$(APP) && npm run build

.PHONY: secrets
secrets:
	@$(TOOLKIT) secrets edit --env $(ENV)

.PHONY: secrets-init
secrets-init:
	@$(TOOLKIT) secrets init --env $(ENV)

.PHONY: secrets-jwks
secrets-jwks:
	@$(TOOLKIT) secrets jwks --env $(ENV)

.PHONY: secrets-hash
secrets-hash:
	@$(TOOLKIT) secrets hash --env $(ENV)

.PHONY: secrets-audit
secrets-audit:
	@$(TOOLKIT) secrets audit

# -----------------------------------------------------------------------------
# Infrastructure (Ansible)
# -----------------------------------------------------------------------------
# Usage:
#   make provision NODE=ace1 ENV=staging               Normal (uses Tailscale IP)
#   make provision NODE=ace1 ENV=staging BOOTSTRAP=1   First run (uses LAN IP from common.yaml)
#   make deploy TARGET=vps ENV=prod
#   make deploy TARGET=k3s ENV=staging
#   make backup ENV=prod

# LAN CIDR from common.yaml (SSOT) — used by BOOTSTRAP to bypass Tailscale routing
_LAN_CIDR = $(shell python3 -c "import yaml; c=yaml.safe_load(open('infra/config/values/common.yaml')); print(c['networking']['lan_cidr'])" 2>/dev/null)

.PHONY: provision
provision:
	@test -n "$(NODE)" || (echo "Usage: make provision NODE=ace1|ace2|rpi4 ENV=staging|prod [BOOTSTRAP=1]" && exit 1)
	@test -n "$(ENV)" || (echo "Usage: make provision NODE=ace1|ace2|rpi4 ENV=staging|prod [BOOTSTRAP=1]" && exit 1)
	@if [ -n "$(BOOTSTRAP)" ]; then \
		echo "=== Bootstrap: LAN route priority over Tailscale (sudo required) ==="; \
		sudo ip rule add to $(_LAN_CIDR) lookup main priority 100 2>/dev/null || true; \
		echo "=== Bootstrap: generating inventory with LAN IPs ==="; \
		$(TOOLKIT) infra ansible generate --env $(ENV) --bootstrap; \
		$(TOOLKIT) infra ansible run -p provision-$(NODE) -e $(ENV) -K; \
		_exit=$$?; \
		echo "=== Restoring: removing LAN route priority ==="; \
		sudo ip rule del to $(_LAN_CIDR) lookup main priority 100 2>/dev/null || true; \
		echo "=== Restoring: inventory with Tailscale IPs ==="; \
		$(TOOLKIT) infra ansible generate --env $(ENV); \
		exit $$_exit; \
	else \
		$(TOOLKIT) infra ansible run -p provision-$(NODE) -e $(ENV) -K; \
	fi

.PHONY: deploy
deploy:
	@test -n "$(TARGET)" || (echo "Usage: make deploy TARGET=vps|dns|k3s ENV=staging|prod" && exit 1)
	@test -n "$(ENV)" || (echo "Usage: make deploy TARGET=vps|dns|k3s ENV=staging|prod" && exit 1)
	@$(TOOLKIT) infra ansible run -p deploy-$(TARGET) -e $(ENV) -K

.PHONY: backup
backup:
	@$(TOOLKIT) infra ansible run -p backup -e $(or $(ENV),prod)

# Helm deploy (ADR-021 — replaces kubectl apply -k)
KUBECONFIG ?= ~/.kube/kubelab-config
HELM_CHART = infra/helm/kubelab

.PHONY: helm-deploy
helm-deploy:
	@test -n "$(ENV)" || (echo "Usage: make helm-deploy ENV=staging|prod" && exit 1)
	@echo "Deploying KubeLab via Helm ($(ENV))..."
	@if [ "$(ENV)" = "prod" ]; then \
		helm upgrade --install kubelab $(HELM_CHART) \
			-f $(HELM_CHART)/values.yaml -f $(HELM_CHART)/values-prod.yaml \
			-n kubelab --create-namespace --kubeconfig $(KUBECONFIG); \
	else \
		helm upgrade --install kubelab $(HELM_CHART) \
			-f $(HELM_CHART)/values.yaml \
			-n kubelab --create-namespace --kubeconfig $(KUBECONFIG); \
	fi

.PHONY: helm-template
helm-template:
	@test -n "$(ENV)" || (echo "Usage: make helm-template ENV=staging|prod" && exit 1)
	@if [ "$(ENV)" = "prod" ]; then \
		helm template kubelab $(HELM_CHART) -f $(HELM_CHART)/values.yaml -f $(HELM_CHART)/values-prod.yaml; \
	else \
		helm template kubelab $(HELM_CHART) -f $(HELM_CHART)/values.yaml; \
	fi

# K8s deploy — Helm for piloted apps + legacy kustomize for remaining services
# When H2 is complete, k8s-apply is removed and deploy-k8s becomes helm-deploy only

.PHONY: deploy-k8s
deploy-k8s:
	@test -n "$(ENV)" || (echo "Usage: make deploy-k8s ENV=staging|prod" && exit 1)
	@echo "=== Deploying K8s workloads ($(ENV)) ==="
	@echo "[1/2] Helm (api, web, errors)..."
	@if [ "$(ENV)" = "prod" ]; then \
		helm upgrade --install kubelab $(HELM_CHART) \
			-f $(HELM_CHART)/values.yaml -f $(HELM_CHART)/values-prod.yaml \
			-n kubelab --create-namespace --kubeconfig $(KUBECONFIG); \
	else \
		helm upgrade --install kubelab $(HELM_CHART) \
			-f $(HELM_CHART)/values.yaml \
			-n kubelab --create-namespace --kubeconfig $(KUBECONFIG); \
	fi
	@echo "[2/2] Kustomize (legacy services)..."
	@kubectl apply -k infra/k8s/overlays/$(ENV)/ --kubeconfig $(KUBECONFIG)
	@echo "✓ All K8s workloads deployed for $(ENV)"

# -----------------------------------------------------------------------------
# Validation & Testing
# -----------------------------------------------------------------------------
.PHONY: smoke-test
smoke-test:
	@$(TOOLKIT) services health --env dev

.PHONY: validate
validate:
	@$(TOOLKIT) config validate

ENV ?= dev

.PHONY: test
test:
	@$(POETRY) run pytest

.PHONY: test-e2e
test-e2e:
	@$(POETRY) run pytest tests/e2e/ -m e2e --env $(ENV) -v --no-cov --override-ini="addopts="

.PHONY: test-infra
test-infra:
	@$(POETRY) run pytest tests/infra/ -m infra --env $(ENV) -v --no-cov --override-ini="addopts="

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
