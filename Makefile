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
	@echo "  make config-generate ENV=x  Generate config files (default: dev)"
	@echo "  make credentials-generate ENV=x  Generate credentials (default: dev)"
	@echo "  make regen-certs        Regenerate dev TLS certs and reinstall browser CA"
	@echo "  make secrets ENV=x      Edit SOPS-encrypted secrets (default: dev)"
	@echo "  make secrets-init ENV=x Generate machine secrets for an env"
	@echo "  make secrets-jwks ENV=x Generate OIDC JWKS RSA key for an env"
	@echo "  make secrets-hash ENV=x Hash all OIDC client secrets"
	@echo "  make secrets-show KEY=x SECRETS_ENV=y  Show a decrypted secret (default: common)"
	@echo "  make secrets-audit      Audit secrets across all environments"
	@echo "  make dev-full-reset     Full teardown + rebuild + restart"
	@echo "  make dev-app APP=x      Start Astro app dev server (site, astro-site)"
	@echo "  make build-app APP=x    Build Astro app (static output)"
	@echo ""
	@echo "Infrastructure (Ansible):"
	@echo "  make provision NODE=x ENV=y  Provision a node (NODE=ace1|ace2|rpi3|rpi4|jetson|vps)"
	@echo "  make deploy TARGET=x ENV=y  Deploy services (TARGET=vps|dns|k3s|harden-nodes)"
	@echo "  make backup ENV=x           Backup VPS volumes (default: prod)"
	@echo ""
	@echo "Monitoring (Uptime Kuma):"
	@echo "  make monitoring-export   Export monitors to JSON (config-as-code)"
	@echo "  make monitoring-import   Import monitors from JSON seed"
	@echo "  make monitoring-apply     Apply monitors from seed JSON (declarative sync)"
	@echo "  make monitoring-bootstrap Bootstrap fresh Uptime Kuma (admin + import)"
	@echo "  make monitoring-status   Check Uptime Kuma status on RPi3"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make sync-homepage      Sync Homepage config from common.yaml"
	@echo "  make sync-k8s-images    Sync image tags from common.yaml to kustomization.yaml"
	@echo "  make sync-oidc-hashes ENV=x  Sync OIDC hashes from SOPS to K8s manifests"
	@echo "  make validate-sync      Check for drift in generated files (ADR-027)"
	@echo "  make apply-secrets ENV=x  Apply SOPS secrets to K8s cluster"
	@echo "  make deploy-k8s ENV=x   Deploy K8s workloads (secrets + sync + manifests)"
	@echo "  make configure-oidc ENV=x  Configure OIDC providers (Gitea) via API"
	@echo "  make backup-pvc ENV=x   Trigger manual PVC backup (ADR-024)"
	@echo "  make flush-sessions ENV=x  Flush Authelia sessions (Redis FLUSHDB)"
	@echo ""
	@echo "Hub (Argo CD):"
	@echo "  make fetch-kubeconfig-hub      Fetch kubeconfig from aws1"
	@echo "  make deploy-argocd             Install/upgrade Argo CD (deploys Authelia OIDC first)"
	@echo "  make deploy-apps               Deploy Argo CD Applications to hub"
	@echo "  make check-apps                Check Application sync status"
	@echo "  make restart-argocd            Restart Argo CD controller (clear cache)"
	@echo "  make register-spoke ENV=x      Register spoke cluster in Argo CD hub"
	@echo "  make unregister-spoke ENV=x    Remove spoke from Argo CD hub"
	@echo "  make check-spokes              Verify registered spokes are reachable"
	@echo "  make rotate-spoke-token ENV=x  Rotate spoke SA token and re-register"
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
	@$(TOOLKIT) tools certs generate --env dev

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
	gitea.kubelab.test n8n.kubelab.test \
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

.PHONY: credentials-generate
credentials-generate:
	@$(TOOLKIT) credentials generate --env $(ENV) --auto-update
	@if [ "$(ENV)" != "dev" ]; then $(TOOLKIT) sync all --env $(ENV); fi

.PHONY: config-generate
config-generate:
	@$(TOOLKIT) config generate --env $(ENV)

.PHONY: build-dev
build-dev:
	@$(TOOLKIT) services build api --env dev --no-cache
	@$(TOOLKIT) services build web --env dev --no-cache
	@$(TOOLKIT) services build errors --env dev --no-cache
	@echo "✓ Development services built"

.PHONY: up-dev
up-dev:
	@$(TOOLKIT) services up \
		api web errors gitea n8n uptime loki grafana authelia crowdsec minio github-runner traefik \
		--env dev
	@echo "✓ Development environment is up"

.PHONY: down-dev
down-dev:
	@echo "--- Bringing down ALL development services and removing volumes ---"
	@$(TOOLKIT) services down \
		api web errors gitea n8n uptime loki grafana authelia crowdsec minio github-runner traefik \
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
	@$(TOOLKIT) services up crowdsec authelia traefik gitea n8n uptime loki grafana api web errors minio github-runner --env dev
	@echo "✓ Development environment fully reset and services are up."
	@echo ""
	@echo "--- Post-start manual steps ---"
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

# -----------------------------------------------------------------------------
# Monitoring (Uptime Kuma)
# -----------------------------------------------------------------------------
.PHONY: monitoring-export
monitoring-export:
	@$(TOOLKIT) monitoring export

.PHONY: monitoring-import
monitoring-import:
	@$(TOOLKIT) monitoring import

.PHONY: monitoring-apply
monitoring-apply:
	@$(TOOLKIT) monitoring apply

.PHONY: monitoring-bootstrap
monitoring-bootstrap:
	@$(TOOLKIT) monitoring bootstrap

.PHONY: monitoring-status
monitoring-status:
	@$(TOOLKIT) monitoring status

.PHONY: secrets-show
secrets-show:
	@ENV=dev $(TOOLKIT) secrets show $(KEY) --env $(or $(SECRETS_ENV),common)

.PHONY: secrets-audit
secrets-audit:
	@$(TOOLKIT) secrets audit

# -----------------------------------------------------------------------------
# Hub (AWS — Argo CD management plane)
# -----------------------------------------------------------------------------
HUB_KUBECONFIG := ~/.kube/kubelab-hub-config

# Fetch kubeconfig from aws1 — auto-accepts new host key (Spot instances rotate)
# Also cleans stale keys for aws1.kubelab.internal from known_hosts
.PHONY: fetch-kubeconfig-hub
fetch-kubeconfig-hub:
	@echo "=== Fetching kubeconfig from aws1 via Tailscale ==="
	@ssh-keygen -R aws1.kubelab.internal 2>/dev/null || true
	@ssh -o StrictHostKeyChecking=accept-new aws1.kubelab.internal "sudo cat /etc/rancher/k3s/k3s.yaml" | \
		sed "s/127.0.0.1/aws1.kubelab.internal/" > $(HUB_KUBECONFIG)
	@chmod 600 $(HUB_KUBECONFIG)
	@echo "✓ Hub kubeconfig saved to $(HUB_KUBECONFIG)"
	@kubectl --kubeconfig $(HUB_KUBECONFIG) get nodes

.PHONY: deploy-argocd
deploy-argocd: _deploy-authelia-oidc _deploy-argocd-helm

# Internal: ensure Authelia has OIDC clients before Argo CD tries to use them
.PHONY: _deploy-authelia-oidc
_deploy-authelia-oidc:
	@echo "=== Step 1/2: Deploying Authelia OIDC config to prod ==="
	@$(TOOLKIT) infra k8s apply-secrets --env prod
	@kubectl --kubeconfig ~/.kube/kubelab-prod-config apply -k infra/k8s/overlays/prod 2>&1 | grep -E 'authelia|error' || true
	@kubectl --kubeconfig ~/.kube/kubelab-prod-config rollout restart deployment/authelia -n kubelab
	@kubectl --kubeconfig ~/.kube/kubelab-prod-config rollout status deployment/authelia -n kubelab --timeout=60s
	@echo "✓ Authelia OIDC ready"

.PHONY: _deploy-argocd-helm
_deploy-argocd-helm:
	@echo "=== Step 2/2: Installing Argo CD on hub (aws1) ==="
	@echo "--- Stopping ALL ArgoCD pods for clean upgrade (t4g.micro OOM mitigation) ---"
	@kubectl --kubeconfig $(HUB_KUBECONFIG) scale deploy --all -n argocd --replicas=0 2>/dev/null || true
	@kubectl --kubeconfig $(HUB_KUBECONFIG) scale statefulset --all -n argocd --replicas=0 2>/dev/null || true
	@echo "--- Waiting for pods to terminate ---"
	@kubectl --kubeconfig $(HUB_KUBECONFIG) wait --for=delete pod -l app.kubernetes.io/part-of=argocd -n argocd --timeout=60s 2>/dev/null || true
	@helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
	@helm repo update argo
	@ARGOCD_HASH=$$(ENV=dev $(POETRY) run toolkit secrets show argocd.admin_password_hash --env common 2>/dev/null | tail -1) && \
	OIDC_SECRET=$$(ENV=dev $(POETRY) run toolkit secrets show apps.services.security.authelia.oidc_client_secret_argocd --env common 2>/dev/null | tail -1) && \
	helm upgrade --install argocd argo/argo-cd \
		--namespace argocd --create-namespace \
		--kubeconfig $(HUB_KUBECONFIG) \
		-f infra/helm/argocd/values.yaml \
		--set "configs.secret.argocdServerAdminPassword=$$ARGOCD_HASH" \
		--set "configs.secret.extra.oidc\.authelia\.clientSecret=$$OIDC_SECRET" \
		--timeout 10m
	@echo "$$(date): Helm upgrade done" >> /tmp/argocd-timing.log
	@echo "--- Updating ArgoCD EndpointSlice on prod (resolve aws1 Tailscale IP via MagicDNS) ---"
	@AWS1_IP=$$(dig +short aws1.kubelab.internal | head -1) && \
	if [ -n "$$AWS1_IP" ]; then \
		sed "s/RESOLVE_AWS1_TAILSCALE_IP/$$AWS1_IP/" infra/k8s/overlays/prod/argocd.yaml | \
			kubectl --kubeconfig ~/.kube/kubelab-prod-config apply -f -; \
		echo "✓ ArgoCD EndpointSlice updated ($$AWS1_IP)"; \
	else \
		echo "⚠ Could not resolve aws1.kubelab.internal — EndpointSlice not updated"; \
	fi
	@echo "✓ Argo CD deployed with OIDC. Login via https://argo.kubelab.live"

# Watch ArgoCD pods until all ready — logs timing to /tmp/argocd-timing.log
# Usage: make watch-argocd (run after deploy-argocd, safe to leave unattended)
.PHONY: watch-argocd
watch-argocd:
	@echo "$$(date): Watching ArgoCD pods..." | tee -a /tmp/argocd-timing.log
	@while true; do \
		READY=$$(kubectl --kubeconfig $(HUB_KUBECONFIG) get pods -n argocd -l app.kubernetes.io/part-of=argocd \
			-o jsonpath='{range .items[*]}{.status.containerStatuses[0].ready}{"\n"}{end}' 2>/dev/null | grep -c true); \
		echo "$$(date): $$READY/5 ready" | tee -a /tmp/argocd-timing.log; \
		[ "$$READY" -ge 5 ] && break; \
		sleep 30; \
	done
	@echo "$$(date): ALL PODS READY ✓" | tee -a /tmp/argocd-timing.log
	@echo "Timing log: /tmp/argocd-timing.log"

# Recover Argo CD from failed Helm upgrade (pending-upgrade state)
# Usage: make recover-argocd
.PHONY: recover-argocd
recover-argocd:
	@echo "=== Checking Argo CD Helm release state ==="
	@STATUS=$$(helm --kubeconfig $(HUB_KUBECONFIG) status argocd -n argocd -o json 2>/dev/null | jq -r '.info.status' 2>/dev/null) && \
	if [ "$$STATUS" = "pending-upgrade" ] || [ "$$STATUS" = "pending-install" ] || [ "$$STATUS" = "pending-rollback" ] || [ "$$STATUS" = "failed" ]; then \
		echo "Release in $$STATUS state — rolling back..."; \
		helm --kubeconfig $(HUB_KUBECONFIG) rollback argocd -n argocd --timeout 5m; \
		echo "✓ Rollback complete. Re-run 'make deploy-argocd' to retry upgrade."; \
	else \
		echo "Release state: $$STATUS — no recovery needed."; \
	fi

# Deploy Argo CD Applications to hub (syncs overlays to spokes)
# Usage: make deploy-apps
.PHONY: deploy-apps
deploy-apps:
	@echo "=== Deploying Argo CD Applications ==="
	@kubectl apply -f infra/k8s/argocd/applications/ --kubeconfig $(HUB_KUBECONFIG)
	@echo "✓ Applications deployed. Check sync status:"
	@echo "  kubectl --kubeconfig $(HUB_KUBECONFIG) -n argocd get applications"

# Check Argo CD Application sync status
.PHONY: check-apps
check-apps:
	@kubectl --kubeconfig $(HUB_KUBECONFIG) -n argocd get applications -o wide 2>/dev/null || echo "No applications found"
	@echo ""
	@for app in $$(kubectl --kubeconfig $(HUB_KUBECONFIG) -n argocd get applications -o name 2>/dev/null); do \
		MSG=$$(kubectl --kubeconfig $(HUB_KUBECONFIG) -n argocd get $$app -o jsonpath='{.status.conditions[*].message}' 2>/dev/null); \
		if [ -n "$$MSG" ]; then \
			echo "--- $$(basename $$app) conditions ---"; \
			echo "$$MSG" | fold -s -w 120; \
			echo ""; \
		fi; \
	done

# Restart Argo CD (controller + server + redis cache flush)
.PHONY: restart-argocd
restart-argocd:
	@echo "=== Flushing Redis cache ==="
	@REDIS_PASS=$$(kubectl --kubeconfig $(HUB_KUBECONFIG) -n argocd get secret argocd-redis -o jsonpath='{.data.auth}' | base64 -d) && \
		kubectl --kubeconfig $(HUB_KUBECONFIG) -n argocd exec deploy/argocd-redis -- redis-cli -a "$$REDIS_PASS" FLUSHALL 2>/dev/null || echo "  Redis flush skipped"
	@echo "=== Restarting Argo CD controller ==="
	@kubectl --kubeconfig $(HUB_KUBECONFIG) -n argocd rollout restart statefulset argocd-application-controller
	@kubectl --kubeconfig $(HUB_KUBECONFIG) -n argocd rollout status statefulset argocd-application-controller --timeout=120s
	@echo "✓ Argo CD restarted (cache flushed)"

# Trigger Argo CD sync for an Application
# Usage: make sync-app APP=kubelab-staging
.PHONY: sync-app
sync-app:
	@test -n "$(APP)" || (echo "Usage: make sync-app APP=kubelab-staging|kubelab-prod" && exit 1)
	@echo "=== Triggering sync for $(APP) ==="
	@kubectl --kubeconfig $(HUB_KUBECONFIG) -n argocd patch application $(APP) --type merge -p '{"operation":{"initiatedBy":{"username":"makefile"},"sync":{"revision":"HEAD"}}}'
	@echo "✓ Sync triggered for $(APP)"

# Register a spoke cluster in Argo CD hub (scoped RBAC, not cluster-admin)
# Usage: make register-spoke ENV=staging|prod
.PHONY: register-spoke
register-spoke:
	@test -n "$(ENV)" || (echo "Usage: make register-spoke ENV=staging|prod" && exit 1)
	@case "$(ENV)" in staging|prod) ;; *) echo "Error: ENV must be staging or prod" && exit 1;; esac
	@echo "=== Cleaning stale RBAC on $(ENV) cluster ==="
	@kubectl --kubeconfig $(KUBECONFIG_PATH) delete clusterrole argocd-manager-cluster-readonly argocd-manager-namespaced --ignore-not-found 2>/dev/null || true
	@kubectl --kubeconfig $(KUBECONFIG_PATH) delete clusterrolebinding argocd-manager-cluster-readonly --ignore-not-found 2>/dev/null || true
	@kubectl --kubeconfig $(KUBECONFIG_PATH) delete rolebinding argocd-manager-namespaced -n kubelab --ignore-not-found 2>/dev/null || true
	@echo "=== Applying spoke RBAC on $(ENV) cluster ==="
	@kubectl apply -f infra/k8s/argocd/spoke-rbac.yaml --kubeconfig $(KUBECONFIG_PATH)
	@echo "--- Waiting for token to be populated..."
	@for i in 1 2 3 4 5; do \
		TOKEN=$$(kubectl get secret argocd-manager-token -n kubelab --kubeconfig $(KUBECONFIG_PATH) -o jsonpath='{.data.token}' 2>/dev/null); \
		if [ -n "$$TOKEN" ]; then break; fi; \
		sleep 2; \
	done
	@echo "--- Verifying RBAC (retry up to 5s for propagation) ---"
	@for i in 1 2 3 4 5; do \
		RESULT=$$(kubectl auth can-i create deployments --as=system:serviceaccount:kubelab:argocd-manager -n kubelab --kubeconfig $(KUBECONFIG_PATH) 2>/dev/null); \
		if [ "$$RESULT" = "yes" ]; then echo "  kubelab: writes OK"; break; fi; \
		sleep 1; \
	done
	@kubectl auth can-i create deployments --as=system:serviceaccount:kubelab:argocd-manager -n kubelab --kubeconfig $(KUBECONFIG_PATH) | grep -q "yes" || (echo "  RBAC check failed: no create in kubelab" && exit 1)
	@kubectl auth can-i list pods --as=system:serviceaccount:kubelab:argocd-manager --kubeconfig $(KUBECONFIG_PATH) | grep -q "yes" && echo "  cluster: reads OK" || echo "  WARNING: no cluster-wide reads"
	@echo "--- Extracting credentials from $(ENV) spoke ---"
	@TOKEN=$$(kubectl get secret argocd-manager-token -n kubelab --kubeconfig $(KUBECONFIG_PATH) -o jsonpath='{.data.token}' | base64 -d) && \
		CA=$$(kubectl get secret argocd-manager-token -n kubelab --kubeconfig $(KUBECONFIG_PATH) -o jsonpath='{.data.ca\.crt}') && \
		SERVER=$$($(POETRY) run python -c "import yaml;c=yaml.safe_load(open('infra/config/values/common.yaml'));n=c['argocd']['spokes']['$(ENV)']['node'];ip=c['networking']['vps']['tailscale_ip'] if n=='vps' else c['networking']['nodes'][n]['tailscale_ip'];print(f'https://{ip}:{c[\"k3s\"][\"api_port\"]}')") && \
		test -n "$$TOKEN" || (echo "Error: token not populated" && exit 1) && \
		test -n "$$CA" || (echo "Error: CA cert not found" && exit 1) && \
		echo "--- Creating cluster secret on hub ($$SERVER) ---" && \
		sed -e "s|CLUSTER_NAME|$(ENV)|g" \
			-e "s|CLUSTER_SERVER|$$SERVER|g" \
			-e "s|BEARER_TOKEN|$$TOKEN|g" \
			-e "s|CA_DATA_BASE64|$$CA|g" \
			infra/k8s/argocd/cluster-secret.yaml.tpl | \
		kubectl apply --kubeconfig $(HUB_KUBECONFIG) -f -
	@echo "--- Verifying registration ---"
	@kubectl get secret cluster-$(ENV) -n argocd --kubeconfig $(HUB_KUBECONFIG) -o jsonpath='{.data.server}' | base64 -d && echo
	@echo "✓ Spoke $(ENV) registered in Argo CD hub"

# Remove spoke from Argo CD hub + cleanup RBAC on spoke
.PHONY: unregister-spoke
unregister-spoke:
	@test -n "$(ENV)" || (echo "Usage: make unregister-spoke ENV=staging|prod" && exit 1)
	@echo "=== Removing $(ENV) spoke from hub ==="
	@kubectl delete secret cluster-$(ENV) -n argocd --kubeconfig $(HUB_KUBECONFIG) --ignore-not-found
	@echo "=== Removing spoke RBAC from $(ENV) cluster ==="
	@kubectl delete -f infra/k8s/argocd/spoke-rbac.yaml --kubeconfig $(KUBECONFIG_PATH) --ignore-not-found
	@echo "✓ Spoke $(ENV) unregistered"

# Verify all registered spokes are reachable (from workstation, not hub)
.PHONY: check-spokes
check-spokes:
	@echo "=== Checking spoke cluster connectivity ==="
	@for env in staging prod; do \
		KC=~/.kube/kubelab-$$env-config; \
		SECRET=$$(kubectl get secret cluster-$$env -n argocd --kubeconfig $(HUB_KUBECONFIG) -o name 2>/dev/null); \
		if [ -z "$$SECRET" ]; then \
			echo "  $$env: NOT REGISTERED"; \
		elif kubectl --kubeconfig $$KC get ns kubelab >/dev/null 2>&1; then \
			echo "  $$env: OK (registered + reachable)"; \
		else \
			echo "  $$env: REGISTERED but UNREACHABLE"; \
		fi; \
	done

# Rotate spoke SA token and re-register on hub
.PHONY: rotate-spoke-token
rotate-spoke-token:
	@test -n "$(ENV)" || (echo "Usage: make rotate-spoke-token ENV=staging|prod" && exit 1)
	@echo "=== Rotating token for $(ENV) spoke ==="
	@kubectl delete secret argocd-manager-token -n kubelab --kubeconfig $(KUBECONFIG_PATH)
	@kubectl apply -f infra/k8s/argocd/spoke-rbac.yaml --kubeconfig $(KUBECONFIG_PATH)
	@echo "--- Waiting for new token..."
	@sleep 3
	@$(MAKE) register-spoke ENV=$(ENV)

# -----------------------------------------------------------------------------
# Infrastructure (Ansible)
# -----------------------------------------------------------------------------
# Usage:
#   make provision NODE=ace1 ENV=staging               Normal (uses Tailscale IP)
#   make provision NODE=ace1 ENV=staging BOOTSTRAP=1   First run (uses LAN IP from common.yaml)
#   make deploy TARGET=vps ENV=prod
#   make deploy TARGET=k3s ENV=staging
#   make backup ENV=prod

.PHONY: provision
provision:
	@test -n "$(NODE)" || (echo "Usage: make provision NODE=ace1|ace2|rpi4|vps [ENV=staging|prod] [BOOTSTRAP=1] [ASK_PASS=1]" && exit 1)
	$(eval _ENV := $(or $(filter staging prod,$(ENV)),staging))
	$(eval _K := $(if $(ASK_PASS),-K,))
	@if [ -n "$(BOOTSTRAP)" ]; then \
		echo "=== Bootstrap: generating inventory with LAN IPs ==="; \
		$(TOOLKIT) infra ansible generate --env $(_ENV) --bootstrap; \
		$(TOOLKIT) infra ansible run -p provision-$(NODE) -e $(_ENV) $(_K); \
		_exit=$$?; \
		echo "=== Restoring: inventory with Tailscale IPs ==="; \
		$(TOOLKIT) infra ansible generate --env $(_ENV); \
		exit $$_exit; \
	else \
		$(TOOLKIT) infra ansible run -p provision-$(NODE) -e $(_ENV) $(_K); \
	fi

.PHONY: deploy
deploy:
	@test -n "$(TARGET)" || (echo "Usage: make deploy TARGET=vps|dns|k3s|harden-nodes ENV=staging|prod" && exit 1)
	@test -n "$(ENV)" || (echo "Usage: make deploy TARGET=vps|dns|k3s|harden-nodes ENV=staging|prod" && exit 1)
	@$(TOOLKIT) infra ansible run -p deploy-$(TARGET) -e $(ENV)

.PHONY: backup
backup:
	@$(TOOLKIT) infra ansible run -p backup -e $(or $(ENV),prod)

# K8s PVC backup — triggers a one-off Job from the CronJob (ADR-024)
# Usage: make backup-pvc ENV=prod
.PHONY: backup-pvc
backup-pvc:
	@test -n "$(ENV)" || (echo "Usage: make backup-pvc ENV=prod" && exit 1)
	@echo "=== Triggering PVC backup ($(ENV)) ==="
	@kubectl create job --from=cronjob/pvc-backup pvc-backup-manual-$$(date +%s) \
		--namespace kubelab --kubeconfig $(KUBECONFIG_PATH)
	@echo "✓ Backup job created. Monitor: kubectl get jobs -n kubelab --kubeconfig $(KUBECONFIG_PATH)"

# K8s deploy — Kustomize for custom apps, Helm for third-party (ADR-021 Rev2)
# Kubeconfig derived from ENV — ignores shell $KUBECONFIG for deterministic behavior
KUBECONFIG_PATH = ~/.kube/kubelab-$(ENV)-config

# AWS Argo CD Hub — Terraform with SOPS-injected secrets
# Usage: make tf-aws-plan   (dry-run)
#        make tf-aws-apply  (create/update infrastructure)
.PHONY: tf-aws-plan tf-aws-apply tf-aws-destroy
tf-aws-plan:
	@$(POETRY) run toolkit infra terraform aws-tfvars
	@cd infra/terraform/aws && terraform plan -var-file=aws.tfvars
	@rm -f infra/terraform/aws/aws.tfvars

tf-aws-apply:
	@$(POETRY) run toolkit infra terraform aws-tfvars
	@cd infra/terraform/aws && terraform apply -auto-approve -var-file=aws.tfvars
	@rm -f infra/terraform/aws/aws.tfvars
	@echo "✓ aws.tfvars cleaned (secrets in SOPS only)"

tf-aws-destroy:
	@$(POETRY) run toolkit infra terraform aws-tfvars
	@cd infra/terraform/aws && terraform destroy -var-file=aws.tfvars
	@rm -f infra/terraform/aws/aws.tfvars

# Terraform DNS (Cloudflare) — SOPS-injected token
.PHONY: tf-dns-plan tf-dns-apply
tf-dns-plan:
	@TOKEN=$$($(POETRY) run toolkit secrets show cloudflare.api_token --env common 2>/dev/null | tail -1) && \
		cd infra/terraform/dns && terraform plan -var-file=dns.tfvars -var="cloudflare_api_token=$$TOKEN"

tf-dns-apply:
	@TOKEN=$$($(POETRY) run toolkit secrets show cloudflare.api_token --env common 2>/dev/null | tail -1) && \
		cd infra/terraform/dns && terraform apply -auto-approve -var-file=dns.tfvars -var="cloudflare_api_token=$$TOKEN"

# sync-homepage regenerates config files from SSOT. Deployment happens via
# `make deploy-k8s` — configMapGenerator hash suffix auto-triggers rolling update.
# No more manual kubectl create/apply/restart (DASH-DT-002, RELIAB-002 pattern).
.PHONY: sync-homepage
sync-homepage:
	@$(TOOLKIT) sync homepage
	@echo "✓ Homepage config regenerated. Run 'make deploy-k8s ENV=x' to deploy."

.PHONY: sync-k8s-images
sync-k8s-images:
	@$(TOOLKIT) sync images

.PHONY: sync-oidc-hashes
sync-oidc-hashes:
	@test -n "$(ENV)" || (echo "Usage: make sync-oidc-hashes ENV=staging|prod" && exit 1)
	@$(TOOLKIT) sync oidc --env $(ENV)

.PHONY: validate-sync
validate-sync:
	@$(TOOLKIT) sync all --check --env $(or $(filter staging prod,$(ENV)),staging)

.PHONY: configure-oidc
configure-oidc:
	@test -n "$(ENV)" || (echo "Usage: make configure-oidc ENV=staging|prod" && exit 1)
	@echo "=== Configuring OIDC providers for $(ENV) ==="
	@$(POETRY) run python toolkit/scripts/configure_oidc.py --env $(ENV)
	@echo "✓ OIDC providers configured for $(ENV)"

.PHONY: apply-secrets
apply-secrets:
	@test -n "$(ENV)" || (echo "Usage: make apply-secrets ENV=staging|prod" && exit 1)
	@$(TOOLKIT) infra k8s apply-secrets --env $(ENV)

.PHONY: flush-sessions
flush-sessions:
	@test -n "$(ENV)" || (echo "Usage: make flush-sessions ENV=staging|prod" && exit 1)
	@echo "Flushing Authelia sessions (Redis) for $(ENV)..."
	@kubectl --kubeconfig ~/.kube/kubelab-$(ENV)-config exec -n kubelab deploy/redis -- redis-cli FLUSHDB
	@echo "✓ Sessions flushed. All users must re-authenticate."

# K8s observability helpers (DEBT-005)
# Usage: make pods ENV=staging
#        make logs SVC=authelia ENV=staging
#        make logs SVC=authelia ENV=staging TAIL=100
# K8s observability — supports staging, prod, and hub (ArgoCD)
# Usage: make pods ENV=staging|prod|hub
#        make logs SVC=authelia ENV=staging [TAIL=50] [FOLLOW=1]
#        make logs SVC=argocd-application-controller-0 ENV=hub
.PHONY: pods
pods:
	@test -n "$(ENV)" || (echo "Usage: make pods ENV=staging|prod|hub" && exit 1)
	$(eval _NS := $(if $(filter hub,$(ENV)),argocd,kubelab))
	@kubectl --kubeconfig ~/.kube/kubelab-$(ENV)-config get pods -n $(_NS) -o wide

.PHONY: logs
logs:
	@test -n "$(SVC)" || (echo "Usage: make logs SVC=authelia ENV=staging|prod|hub [TAIL=50] [FOLLOW=1]" && exit 1)
	$(eval _ENV := $(or $(filter staging prod hub,$(ENV)),staging))
	$(eval _NS := $(if $(filter hub,$(_ENV)),argocd,kubelab))
	$(eval _TAIL := $(or $(TAIL),50))
	$(eval _FOLLOW := $(if $(FOLLOW),-f,))
	@kubectl --kubeconfig ~/.kube/kubelab-$(_ENV)-config logs -n $(_NS) $(SVC) --tail=$(_TAIL) $(_FOLLOW)

.PHONY: deploy-k8s
deploy-k8s: apply-secrets validate-sync
	@test -n "$(ENV)" || (echo "Usage: make deploy-k8s ENV=staging|prod" && exit 1)
	@$(TOOLKIT) infra k8s deploy --env $(ENV)

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
check: lint type test validate-sync
	@echo "✓ All checks passed"
