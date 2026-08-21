# =============================================================================
# Makefile – Minimal bootstrap and top-level orchestration
# =============================================================================
# This Makefile provides ONLY:
#   1. Bootstrap (setup Python, Poetry, toolkit)
#   2. Help/discovery
#   3. Top-level convenience aliases
#
# For all other operations, use toolkit directly:
#   toolkit services up gitea
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
	@echo "  make worktree-init      Bootstrap a new git worktree (poetry install only; idempotent)"
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
	@echo "  make dev-app APP=x      Start Astro app dev server (site)"
	@echo "  make build-app APP=x    Build Astro app (static output)"
	@echo ""
	@echo "Infrastructure (Ansible):"
	@echo "  make provision NODE=x ENV=y  Provision a node (NODE=ace1|ace2|aws1|bee|rpi3|rpi4|jetson|vps, ENV=staging|prod|hub) [TAGS=tag1,tag2] [EXTRA='k=v']"
	@echo "  make maintain NODE=x         Disk cleanup (NODE=aws1|ace1|ace2|beelink|vps|all) [TIMER=1] [TAGS=tag1,tag2]"
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
	@echo "  make fetch-kubeconfig ENV=x   Fetch a cluster kubeconfig (staging|prod|hub)"
	@echo "  make deploy-argocd             Install/upgrade Argo CD (deploys Authelia OIDC first)"
	@echo "  make deploy-apps               Deploy Argo CD Applications to hub"
	@echo "  make check-apps                Check Application sync status"
	@echo "  make restart-argocd            Restart Argo CD controller (clear cache)"
	@echo "  make register-spoke ENV=x      Register spoke cluster in Argo CD hub"
	@echo "  make unregister-spoke ENV=x    Remove spoke from Argo CD hub"
	@echo "  make argo-set-revision APP=x REV=y  Patch Application targetRevision (preview/patch-back)"
	@echo "  make check-spokes              Verify registered spokes are reachable"
	@echo "  make rotate-spoke-token ENV=x  Rotate spoke SA token and re-register"
	@echo ""
	@echo "Quality:"
	@echo "  make check              Run all checks (lint + type + test)"
	@echo "  make lint               Ruff linting (check only)"
	@echo "  make lint-ansible       Parse every Ansible playbook without running it"
	@echo "  make format             Ruff formatting (auto-fix)"
	@echo "  make type               Mypy type checking"
	@echo "  make test               Run pytest suite (unit/integration only)"
	@echo "  make test-fast          Same, minus the container-backed integration tests"
	@echo "  make test-e2e ENV=x     Run e2e tests (ENV=dev|staging|prod)"
	@echo "  make test-infra ENV=x   Run infra tests (ENV=staging|prod, requires VPN)"
	@echo "  make validate           Validate toolkit config"
	@echo "  make smoke-test         Health check running services"
	@echo ""
	@echo "Toolkit CLI (use directly for most operations):"
	@echo "  toolkit services up gitea        Start Gitea"
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

# worktree-init bootstraps a fresh git worktree to first-class status:
# poetry install populates `.venv` (per-worktree); pre-commit hooks are NOT
# reinstalled because the repo already has `core.hooksPath = main/.git/hooks`
# (one-time set during `make setup`), which all worktrees share automatically.
# Idempotent: re-running in an already-bootstrapped worktree is ~1s no-op.
# Discovered as TOOL-010 after Wave 1 DT-010 PR hit `make sync-homepage`
# failures in a fresh worktree (no .venv -> toolkit package not importable).
.PHONY: worktree-init
worktree-init:
	@echo "=== Bootstrapping worktree: $$(pwd) ==="
	@$(POETRY) install --no-interaction
	@hookspath=$$(git config --get core.hooksPath 2>/dev/null || echo ""); \
	if [ -n "$$hookspath" ] && [ -x "$$hookspath/pre-commit" ]; then \
		echo "✓ pre-commit hooks shared from $$hookspath (no re-install needed)"; \
	else \
		echo "⚠ core.hooksPath not set or pre-commit hook missing — run from main worktree: $(POETRY) run pre-commit install"; \
	fi
	@echo "✓ Worktree ready. Test: make validate-sync ENV=staging"

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

# CI-GATE-002/003: detect drift between the generator output and the committed
# `generated/` files. Catches the class of bug that bit SEC-K8S-001 (prod
# ingress.yaml lacked secure-headers middleware because the generator code
# evolved but the committed file was never refreshed).
#
# Scope (SOPS-independent only — safe for CI without an age key):
#   - infra/k8s/overlays/<env>/generated/ingress.yaml      (CI-GATE-002)
#   - infra/ansible/generated/<env>/hosts.yml              (CI-GATE-002)
#   - infra/k8s/overlays/<env>/generated/configmaps.yaml   (CI-GATE-003)
#
# These generators read EXCLUSIVELY from `common.yaml` + `<env>.yaml`
# (post-SSOT-012, configmaps.yaml no longer pulls non-secret values from
# SOPS), so the gate is deterministic in CI without decryption.
#
# NOT included (each has a specific reason):
#   - deployments.yaml — committed, but the generator omits `secretRef`
#     refs when SOPS decryption fails. Drift-checking without an age key
#     produces false positives. Tracked as SSOT-018 (refactor generator
#     to emit secretRef from SOPS file presence, not decryption success).
#   - edge/traefik/generated/<env>/dynamic/middlewares.yml — gitignored
#     (embeds plaintext basic_auth credentials). Drift-check is no-op.
#   - infra/config/authelia/generated/<env>/configuration.yml — gitignored
#     (embeds plaintext jwt_secret + argon2 hashes). Drift-check is no-op.
#
# KNOWN VACUOUS PATH: `infra/ansible/generated/<env>/hosts.yml` is listed below
# and checks nothing. `infra/ansible/.gitignore:6` says "Generated Ansible
# configurations (NEVER commit these)" and `git log --all` confirms the file was
# never tracked, so `git diff` cannot see it — CI-GATE-002's Ansible half was
# born vacuous rather than broken later. Left in place here, annotated rather
# than silently removed, because deciding how Ansible inventory drift *should*
# be detected is a separate call. Tracked as #1048.

# Paths the revert at the end of `config-check-drift` may touch: exactly the
# generator's TRACKED output, nothing else.
#
# This used to be `git checkout -- infra edge`, which reverted two whole trees
# and so discarded any uncommitted hand edit under them — including
# `infra/config/values/*.yaml`, the repo's declared source of truth. It
# destroyed real work while printing "✓ No drift" (#1034), and `git checkout --`
# on unstaged changes is the one git operation with no undo.
#
# The generator also writes `edge/traefik/generated/`, `infra/ansible/generated/`
# and `infra/config/authelia/generated/`. Those are deliberately absent: all
# three are gitignored with zero tracked files, so `git checkout --` errors on
# them (which is what the old `2>/dev/null || true` was really swallowing) and
# their residue is invisible to `git status` anyway.
#
# Whole directories, not just the three files diffed below: a run without an age
# key rewrites the *tracked* `deployments.yaml` with its `secretRef`s omitted,
# and that file is deliberately excluded from the diff. Only this revert puts it
# back, so narrowing to the diffed paths would leave a mutilated tracked file
# behind on every keyless run.
DRIFT_REVERT_PATHS := infra/k8s/overlays/staging/generated \
                      infra/k8s/overlays/prod/generated

# The environments this gate can actually check — not "every environment".
# Only these have an `infra/k8s/overlays/<env>/generated/` tree, so only for
# these does the diff below have anything to compare. `dev` generates Docker
# Compose configs instead, so pointing the gate at it makes `git diff` run over
# pathspecs that match nothing, which exits 0 and prints "✓ No drift" no matter
# what the generator did.
DRIFT_ENVS := staging prod

# Validate the ENV *value* against DRIFT_ENVS, not merely its provenance.
#
# Two weaker guards shipped here before, and both were reachable no-ops.
# `test -n "$(ENV)"` never failed, because `ENV ?= dev` — 700 lines further down,
# but global regardless of position — made `$(ENV)` expand to `dev`; a bare
# `make config-check-drift` checked the dev overlay and reported green while
# staging and prod both drifted, which is how #1116 reached CI with a
# `common.yaml` key that rewrote every component's ConfigMap (#1118). Replacing
# it with `test "$(origin ENV)" = "command line"` only moved the hole: `ENV=`
# also has command-line origin, and `ENV=dev` passed by design straight into
# the vacuous-pathspec case above.
#
# `$(words)` rejects both the empty value and a multi-word one like
# `ENV="staging prod"`, which `$(filter)` alone would accept and then splice
# unquoted into the generator's argv.
.PHONY: config-check-drift
config-check-drift:
	@{ test "$(words $(ENV))" = 1 \
	   && test -n "$(filter $(ENV),$(DRIFT_ENVS))"; } || { \
		echo "Usage: make config-check-drift ENV=<one of: $(DRIFT_ENVS)>"; \
		echo "  Got ENV='$(ENV)'. Only these environments have a committed"; \
		echo "  K8s overlay for the check to diff against, so any other value"; \
		echo "  — including the repo-wide 'ENV ?= dev' default — would diff an"; \
		echo "  empty pathspec and report green whatever the generator did."; \
		exit 1; \
	}
	@git diff --quiet -- $(DRIFT_REVERT_PATHS) || { \
		echo "✗ Refusing to run: uncommitted changes under $(DRIFT_REVERT_PATHS)"; \
		echo "  This target reverts those paths when it finishes, which would"; \
		echo "  discard them. Commit or stash first."; \
		exit 1; \
	}
	@echo "→ Regenerating $(ENV) configs and checking for drift..."
	@$(TOOLKIT) config generate --env $(ENV) --force
	@_status=0; \
	_paths="infra/k8s/overlays/$(ENV)/generated/ingress.yaml \
	        infra/k8s/overlays/$(ENV)/generated/configmaps.yaml \
	        infra/ansible/generated/$(ENV)/hosts.yml"; \
	if git diff --quiet -- $$_paths; then \
		echo "✓ No drift in $(ENV) generated configs"; \
	else \
		echo "✗ Drift detected in $(ENV) generated configs:"; \
		git --no-pager diff -- $$_paths; \
		_status=1; \
	fi; \
	git checkout -- $(DRIFT_REVERT_PATHS); \
	exit $$_status

.PHONY: build-dev
build-dev:
	@$(TOOLKIT) services build api --env dev --no-cache
	@$(TOOLKIT) services build errors --env dev --no-cache
	@echo "✓ Development services built"

.PHONY: up-dev
up-dev:
	@$(TOOLKIT) services up \
		api errors gitea n8n uptime loki grafana authelia crowdsec minio github-runner traefik \
		--env dev
	@echo "✓ Development environment is up"

.PHONY: down-dev
down-dev:
	@echo "--- Bringing down ALL development services and removing volumes ---"
	@$(TOOLKIT) services down \
		api errors gitea n8n uptime loki grafana authelia crowdsec minio github-runner traefik \
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
	@$(TOOLKIT) services up crowdsec authelia traefik gitea n8n uptime loki grafana api errors minio github-runner --env dev
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

.PHONY: sync-secret-manager
sync-secret-manager: ## Deliver the GCP hub's boot secrets to Secret Manager (one-way; SOPS stays SSOT)
	@$(TOOLKIT) secrets sync-secret-manager

.PHONY: sync-secret-manager-dry
sync-secret-manager-dry: ## Same, but compare and report without writing
	@$(TOOLKIT) secrets sync-secret-manager --dry-run

# -----------------------------------------------------------------------------
# Hub (AWS — Argo CD management plane)
# -----------------------------------------------------------------------------
HUB_KUBECONFIG := ~/.kube/kubelab-hub-config

# Fetch a cluster's kubeconfig (ADR-052): transport-agnostic server
# (https://127.0.0.1:<local_port>) -> ~/.kube/kubelab-<ENV>-config.
# Unifies the old inline hub-only fetch. ENV=staging|prod|hub.
.PHONY: fetch-kubeconfig
fetch-kubeconfig:
	@$(TOOLKIT) infra k8s fetch-kubeconfig --env $(ENV)

# Cluster-access transport (ADR-052 Phase 2): map 127.0.0.1:<local_port> to the
# env's apiserver -- ts-bridge over the mesh (staging|hub) or the direct public
# endpoint (prod). Idempotent. ENV=staging|prod|hub (the toolkit rejects others).
.PHONY: connect
connect:
	@$(TOOLKIT) infra k8s access connect --env $(ENV)

.PHONY: disconnect
disconnect:
	@$(TOOLKIT) infra k8s access disconnect --env $(ENV)

.PHONY: connect-status
connect-status:
	@$(TOOLKIT) infra k8s access status --env $(ENV)

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
	SLACK_WEBHOOK=$$(ENV=dev $(POETRY) run toolkit secrets show argocd.slack_webhook_url --env common 2>/dev/null | tail -1) && \
	GH_WEBHOOK_SECRET=$$(ENV=dev $(POETRY) run toolkit secrets show argocd.github_webhook_secret --env common 2>/dev/null | tail -1) && \
	test -n "$$ARGOCD_HASH"       || { echo "FATAL: argocd.admin_password_hash decrypted empty — refusing to install Argo CD with a blank admin password (check SOPS age key)" >&2; exit 1; } && \
	test -n "$$OIDC_SECRET"       || { echo "FATAL: oidc_client_secret_argocd decrypted empty — refusing to install Argo CD with blank OIDC (check SOPS age key)" >&2; exit 1; } && \
	test -n "$$SLACK_WEBHOOK"     || { echo "FATAL: argocd.slack_webhook_url decrypted empty — refusing to install (check SOPS age key)" >&2; exit 1; } && \
	test -n "$$GH_WEBHOOK_SECRET" || { echo "FATAL: argocd.github_webhook_secret decrypted empty — refusing to install (check SOPS age key)" >&2; exit 1; } && \
	ARGOCD_CHART=$$($(TOOLKIT) config get argocd.chart_version) && \
	test -n "$$ARGOCD_CHART" || { echo "FATAL: argocd.chart_version missing from common.yaml — refusing to install an unpinned chart" >&2; exit 1; } && \
	helm upgrade --install argocd argo/argo-cd \
		--version "$$ARGOCD_CHART" \
		--namespace argocd --create-namespace \
		--kubeconfig $(HUB_KUBECONFIG) \
		-f infra/helm/argocd/values.yaml \
		--set "configs.secret.argocdServerAdminPassword=$$ARGOCD_HASH" \
		--set "configs.secret.extra.oidc\.authelia\.clientSecret=$$OIDC_SECRET" \
		--set "notifications.secret.items.slack-webhook-url=$$SLACK_WEBHOOK" \
		--set "configs.secret.githubSecret=$$GH_WEBHOOK_SECRET" \
		--timeout 10m
	@echo "$$(date): Helm upgrade done" >> /tmp/argocd-timing.log
	@echo "--- Updating ArgoCD EndpointSlice on prod (MagicDNS-resolved aws1 Tailscale IP) ---"
	@$(TOOLKIT) infra k8s render-apply --env prod --optional \
		--manifest infra/k8s/overlays/prod/argocd-endpointslice.yaml \
		--render RESOLVE_AWS1_TAILSCALE_IP=aws1.kubelab.internal
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

# `deploy-external` removed (ADR-047 / TOOL-009). Its two actions are now covered by
# `make deploy-k8s ENV=x`:
#   - coredns-custom (RPi4 hairpin DNS, MagicDNS-rendered) → the cluster_bootstrap layer.
#   - external EndpointSlices (pihole / uptime-kuma) → the Kustomize base.
# The aws1 (argocd) EndpointSlice render moved to `toolkit infra k8s render-apply`
# inside `_deploy-argocd-helm`. No more inline dig|sed|kubectl in this Makefile.

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
	@echo "--- Verifying the live objects now match git (#1016) ---"
	@$(TOOLKIT) infra argo check-drift --kubeconfig $(HUB_KUBECONFIG)
	@echo "✓ Applications deployed and verified clean. Check sync status:"
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
	@echo "=== Drift check: live Applications vs git (#1016) ==="
	@$(TOOLKIT) infra argo check-drift --kubeconfig $(HUB_KUBECONFIG)

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

# Patch an Argo CD Application's spec.source.targetRevision (preview-per-PR + patch-back).
# Usage: make argo-set-revision APP=kubelab-staging REV=master
.PHONY: argo-set-revision
argo-set-revision:
	@test -n "$(APP)" || (echo "Usage: make argo-set-revision APP=kubelab-staging REV=master" && exit 1)
	@test -n "$(REV)" || (echo "Usage: make argo-set-revision APP=kubelab-staging REV=master" && exit 1)
	@$(TOOLKIT) infra argo set-revision --app $(APP) --rev $(REV)

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
#   make provision NODE=ace1 ENV=staging                  Normal (uses Tailscale IP)
#   make provision NODE=ace1 ENV=staging BOOTSTRAP=1      First run (uses LAN IP from common.yaml)
#   make provision NODE=ace2 ENV=staging TRANSPORT=bastion  From a non-mesh controller (TOOL-016, jump via VPS)
#   make deploy TARGET=vps ENV=prod
#   make deploy TARGET=k3s ENV=staging
#   make backup ENV=prod

.PHONY: provision
provision:
	@test -n "$(NODE)" || (echo "Usage: make provision NODE=ace1|ace2|aws1|rpi4|vps [ENV=staging|prod|hub] [BOOTSTRAP=1] [TRANSPORT=bastion] [CHECK=1] [ASK_PASS=1] [TAGS=tag1,tag2] [EXTRA='k=v k2=v2']" && exit 1)
	$(eval _ENV := $(or $(filter staging prod hub,$(ENV)),staging))
	$(eval _K := $(if $(ASK_PASS),-K,))
	$(eval _TAGS := $(if $(TAGS),--tags $(TAGS),))
	$(eval _BOOT := $(if $(BOOTSTRAP),--bootstrap,))
	$(eval _TRANSPORT := $(if $(TRANSPORT),--transport $(TRANSPORT),))
	$(eval _CHECK := $(if $(CHECK),--check,))
	# EXTRA passes Ansible extra-vars through for role switches that must be
	# opted into per run rather than defaulted on -- e.g. a role that reboots
	# the host. Without it the only way to set one is a raw ansible-playbook
	# invocation, which is exactly what these targets exist to prevent.
	$(eval _EXTRA := $(if $(EXTRA),--extra-vars "$(EXTRA)",))
	# The generate below is joined to the run with `&&`, not `;`: a failed
	# generate must not let the playbook proceed against whatever inventory is
	# left on disk. It also makes _exit capture generate's failure, because $$?
	# of `a && b` is a's status when a fails. The restore line stays `;` — it
	# has to run either way. See TOOL-036.
	@if [ -n "$(BOOTSTRAP)" ] || [ -n "$(TRANSPORT)" ]; then \
		echo "=== Generating inventory ($(if $(BOOTSTRAP),LAN IPs,mesh)$(if $(TRANSPORT), via $(TRANSPORT),)) ==="; \
		$(TOOLKIT) infra ansible generate --env $(_ENV) $(_BOOT) $(_TRANSPORT) && \
		$(TOOLKIT) infra ansible run -p provision-$(NODE) -e $(_ENV) $(_K) $(_TAGS) $(_CHECK) $(_EXTRA); \
		_exit=$$?; \
		echo "=== Restoring: inventory with mesh Tailscale IPs ==="; \
		$(TOOLKIT) infra ansible generate --env $(_ENV); \
		exit $$_exit; \
	else \
		$(TOOLKIT) infra ansible run -p provision-$(NODE) -e $(_ENV) $(_K) $(_TAGS) $(_CHECK) $(_EXTRA); \
	fi

.PHONY: maintain
maintain:
	@test -n "$(NODE)" || (echo "Usage: make maintain NODE=aws1|ace1|ace2|beelink|vps|rpi3|rpi4|all [TIMER=1] [TAGS=tag1,tag2] [CHECK=1]" && exit 1)
	$(eval _ENV := $(or $(filter staging prod,$(ENV)),staging))
	$(eval _TIMER := $(if $(TIMER),--extra-vars "install_timer=true",))
	$(eval _TAGS := $(if $(TAGS),--tags $(TAGS),))
	$(eval _CHECK := $(if $(CHECK),--check,))
	@if [ "$(NODE)" = "all" ]; then \
		$(TOOLKIT) infra ansible run -p maintain -e $(_ENV) $(_TIMER) $(_TAGS) $(_CHECK); \
	else \
		$(TOOLKIT) infra ansible run -p maintain -e $(_ENV) -l $(NODE) $(_TIMER) $(_TAGS) $(_CHECK); \
	fi

# Live delivery test of the maintenance failure-notify path (ANSIBLE-035 AC7).
# Really posts to prod n8n and really notifies — a delivery test that suppresses
# delivery proves nothing. Re-run this after any change to the notify script or
# its unit; ANSIBLE-038's fix requires it.
#
# EXTRA reaches the playbook's `notify_test_unit`, which selects WHICH unit's
# failure is being simulated — the notifier is one template unit shared by the
# fleet, so `kubelab-maintenance.service` is a default rather than the subject:
#
#   make maintain-notify-test NODE=rpi3 ENV=prod \
#     EXTRA='notify_test_unit=node-backup-ship.service'
#
# The `EXTRA=` spelling is the one `make provision` already uses. The playbook
# gained the variable before any target could pass it, which made the override
# documented and unreachable.
.PHONY: maintain-notify-test
maintain-notify-test:
	@test -n "$(NODE)" || (echo "Usage: make maintain-notify-test NODE=aws1|ace1|ace2|beelink|vps|rpi3|rpi4|all [ENV=staging|prod|hub] [EXTRA='notify_test_unit=<unit>']" && exit 1)
	$(eval _ENV := $(or $(filter staging prod hub,$(ENV)),staging))
	$(eval _EXTRA := $(if $(EXTRA),--extra-vars "$(EXTRA)",))
	@if [ "$(NODE)" = "all" ]; then \
		$(TOOLKIT) infra ansible run -p maintenance-notify-test -e $(_ENV) $(_EXTRA); \
	else \
		$(TOOLKIT) infra ansible run -p maintenance-notify-test -e $(_ENV) -l $(NODE) $(_EXTRA); \
	fi

.PHONY: deploy
deploy:
	@test -n "$(TARGET)" || (echo "Usage: make deploy TARGET=vps|dns|k3s|harden-nodes ENV=staging|prod [CHECK=1]" && exit 1)
	@test -n "$(ENV)" || (echo "Usage: make deploy TARGET=vps|dns|k3s|harden-nodes ENV=staging|prod [CHECK=1]" && exit 1)
	$(eval _CHECK := $(if $(CHECK),--check,))
	@$(TOOLKIT) infra ansible run -p deploy-$(TARGET) -e $(ENV) $(_CHECK)

# CHECK=1 is a dry run. It is accepted HERE, and on every other target that
# changes a node, because `make provision` accepted it and these did not:
# `make backup ENV=prod CHECK=1` silently ignored the flag and deployed to all
# four prod nodes for real. make has no notion of an unknown variable, so the
# only signal was the absence of one. Asserted in tests/test_makefile_dry_run.py.
.PHONY: backup
backup:
	$(eval _CHECK := $(if $(CHECK),--check,))
	@$(TOOLKIT) infra ansible run -p backup -e $(or $(ENV),prod) $(_CHECK)

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

# aws1 lifecycle wrappers — cancel the underlying Spot Persistent Request
# BEFORE terraform destroy/replace. Without this, AWS keeps the request
# active and relaunches a replacement instance after terraform terminates
# the EC2, costing money and creating zombie nodes outside Terraform.
# The Spot Request is orphaned from state since the AWS-003 refactor
# (state rm aws_spot_instance_request + import aws_instance) — it lives
# in AWS only and must be cancelled out-of-band.
.PHONY: aws1-destroy aws1-replace _aws1-cancel-spot-request
_aws1-cancel-spot-request:
	@SIR=$$(cd infra/terraform/aws && terraform output -raw spot_request_id 2>/dev/null) && \
		if [ -n "$$SIR" ] && [ "$$SIR" != "null" ]; then \
			echo "Cancelling Spot Persistent Request $$SIR..." && \
			aws ec2 cancel-spot-instance-requests \
				--spot-instance-request-ids $$SIR \
				--profile kubelab --region eu-central-1 \
				--output text >/dev/null && \
			echo "✓ Spot Request cancelled"; \
		else \
			echo "No spot_request_id in terraform state — skipping cancellation"; \
		fi

aws1-destroy: _aws1-cancel-spot-request tf-aws-destroy

# ANSIBLE-041 (#1102): this target used to stop after terraform and print
# "Wait ~5 min for cloud-init, then run: make deploy-argocd". That instruction
# was both manual and incomplete — it never named `provision-aws1`, which is
# where the node_maintenance role lives, so every replacement silently produced
# a hub with no maintenance timer and no failure-notify path. The absence was
# invisible in the direction it failed: no timer means no maintenance failures,
# so the missing notifier was never exercised either.
aws1-replace: _aws1-cancel-spot-request
	@$(POETRY) run toolkit infra terraform aws-tfvars
	@cd infra/terraform/aws && terraform apply -auto-approve -var-file=aws.tfvars -replace=aws_instance.argo_hub
	@rm -f infra/terraform/aws/aws.tfvars
	@$(MAKE) --no-print-directory wait-node-ready NODE=aws1 ENV=hub
	@$(MAKE) --no-print-directory provision NODE=aws1 ENV=hub
	@$(MAKE) --no-print-directory deploy-argocd
	@echo "✓ aws1 replaced, provisioned and reconciling."

# Block until a node can actually be provisioned: sshd answering AND cloud-init
# finished. Two conditions, not one — sshd comes up long before cloud-init has
# installed K3s and registered Tailscale. The logic lives in the playbook, not
# here, so the Makefile keeps no inline shell.
.PHONY: wait-node-ready
wait-node-ready:
	@test -n "$(NODE)" || (echo "Usage: make wait-node-ready NODE=aws1|ace1|ace2|beelink|vps|rpi3|rpi4 [ENV=staging|prod|hub]" && exit 1)
	$(eval _ENV := $(or $(filter staging prod hub,$(ENV)),staging))
	@$(TOOLKIT) infra ansible run -p wait-node-ready -e $(_ENV) -l $(NODE)

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

# Refresh vendored cluster_bootstrap operator manifests from their SSOT-pinned
# version (ADR-047 / TOOL-009). Bump the entry's `version` in common.yaml, then run.
.PHONY: sync-operators
sync-operators:
	@$(TOOLKIT) sync operators

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

# Restart any K8s deployment via the toolkit (rollout restart + wait). Generic over
# service + namespace (NS defaults to kubelab). E.g. make a pod re-read a changed
# env-var Secret: make restart-service SVC=traefik ENV=staging NS=kube-system
.PHONY: restart-service
restart-service:
	@test -n "$(SVC)" || (echo "Usage: make restart-service SVC=<deployment> ENV=staging|prod [NS=namespace]" && exit 1)
	@test -n "$(ENV)" || (echo "Usage: make restart-service SVC=<deployment> ENV=staging|prod [NS=namespace]" && exit 1)
	@$(TOOLKIT) infra k8s restart $(SVC) --env $(ENV) $(if $(NS),--namespace $(NS),)

# Renders Traefik Middlewares that wrap SOPS-sourced API keys (ADR-035 Stage 1).
# MIDDLEWARE_CATALOG is empty since AI-007 retired Ollama, Stage 1's first
# consumer — this target is a no-op until the next one registers. Adding a new
# auth-protected service:
#   1. Append a SecretSpec to SECRET_CATALOG (toolkit/features/secrets_manager.py)
#   2. Append a MiddlewareSpec to MIDDLEWARE_CATALOG (toolkit/features/k8s_middlewares.py)
#   3. Put the api_key in SOPS, then `make apply-middleware-secrets ENV=prod`
.PHONY: apply-middleware-secrets
apply-middleware-secrets:
	@test -n "$(ENV)" || (echo "Usage: make apply-middleware-secrets ENV=staging|prod" && exit 1)
	@$(TOOLKIT) infra k8s apply-middleware-secrets --env $(ENV)

# Reconstructs the n8n notify-router workflow + Header Auth credential from
# Git (workflow JSON) + SOPS (webhook_secret) — TOOL-009. Idempotent upsert via
# fixed ids in the workflow JSON. Secret reaches the pod via /dev/shm only.
# Auto-runs as the last step of deploy-k8s; staging-only today (no-op elsewhere).
.PHONY: import-n8n
import-n8n:
	@test -n "$(ENV)" || (echo "Usage: make import-n8n ENV=staging" && exit 1)
	@$(TOOLKIT) infra n8n import --env $(ENV)

# End-to-end smoke of the notification fabric (NOTIFY-001): POSTs page + log
# envelopes to the real n8n webhook with the Bearer secret from SOPS, asserts
# HTTP 200 (routed + delivered) and that an unauthenticated POST is rejected
# (403). Confirm the messages land in Telegram. Staging-only today.
.PHONY: notify-smoke
notify-smoke:
	@test -n "$(ENV)" || (echo "Usage: make notify-smoke ENV=staging" && exit 1)
	@$(TOOLKIT) infra n8n smoke --env $(ENV)

# Prove the offsite backup destination (Cloudflare R2) is usable: that the token
# is scoped to its own bucket, that the bucket is reachable, and that a
# write/read/DELETE round-trip succeeds. Writes 1 KB under `_smoketest/` and
# removes it, so it is safe against the live destination.
#
# The delete probe is the one that pays for itself: a token without delete lets
# backups report healthy for weeks, and only fails when `restic forget` first
# tries to reclaim space — with a full bucket and a retention policy that has
# never actually retained anything (BACKUP-044).
.PHONY: backup-verify-destination
backup-verify-destination:
	@$(TOOLKIT) backup verify-destination --env $(or $(ENV),prod)

# One level above backup-verify-destination: that one proves the BUCKET works,
# this one proves RESTIC works in it. Runs the full lifecycle (init, backup,
# snapshots, check) against a throwaway repository and removes it. They are
# different claims and only the second is what backups depend on.
.PHONY: backup-verify-restic
backup-verify-restic:
	@$(TOOLKIT) backup verify-restic --env $(or $(ENV),prod)

# Generate the restic repository password into SOPS. The value is never printed;
# read it once with `make secrets-show KEY=backup.restic_password
# SECRETS_ENV=common` to place the offsite escrow copy. Refuses to overwrite an
# existing password: replacing it without `restic key add` first locks you out of
# every existing snapshot.
.PHONY: backup-generate-password
backup-generate-password:
	@$(TOOLKIT) backup generate-password --env $(or $(SECRETS_ENV),common)

# End-to-end smoke of the certificate ALERTING path (OBS-007), one layer above
# notify-smoke: that one proves the fabric can deliver, this one proves the alert
# rule notices a real failure and recovers from it. Induces a genuine ACME
# failure with a throwaway route, waits for the rule to fire and notify, tears it
# down, and waits for the resolved message. Takes 10-20 minutes — the rule
# evaluates every 5m with a 5m pending period. Staging only; prod pages.
.PHONY: alert-smoke
alert-smoke:
	@test -n "$(ENV)" || (echo "Usage: make alert-smoke ENV=staging" && exit 1)
	@$(TOOLKIT) infra k8s alert-smoke --env $(ENV)

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
deploy-k8s: apply-secrets apply-middleware-secrets validate-sync
	@test -n "$(ENV)" || (echo "Usage: make deploy-k8s ENV=staging|prod" && exit 1)
	@$(TOOLKIT) infra k8s deploy --env $(ENV)
	@$(MAKE) import-n8n ENV=$(ENV) || echo "⚠️  n8n workflow import failed after a successful K8s deploy — the deploy itself is fine; re-run: make import-n8n ENV=$(ENV)"

# Apply ONLY the cluster-wide bootstrap layer (cluster_bootstrap SSOT, ADR-047/TOOL-009):
# CRDs/operators/kube-system config outside the Argo CD overlay, without touching workloads.
.PHONY: bootstrap-k8s
bootstrap-k8s:
	@test -n "$(ENV)" || (echo "Usage: make bootstrap-k8s ENV=staging|prod" && exit 1)
	@$(TOOLKIT) infra k8s bootstrap --env $(ENV)

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

# `test` stays the complete local suite — CI runs this target, so anything
# excluded here is excluded from CI too. The integration tests start a real
# Uptime Kuma container (~90s); `test-fast` skips them for the inner loop, but
# the safe option is the default one on purpose.
.PHONY: test
test:
	@$(POETRY) run pytest

.PHONY: test-fast
test-fast:
	@$(POETRY) run pytest -m "not e2e and not infra and not integration"

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

.PHONY: lint-ansible
lint-ansible: ## Parse every Ansible playbook without running it (needs Galaxy collections)
	@$(TOOLKIT) infra ansible syntax-check

.PHONY: type
type:
	@$(POETRY) run mypy toolkit

.PHONY: check-headscale-policy
check-headscale-policy: ## Render + validate the Headscale ACL policy (headscale policy check via Docker)
	@$(TOOLKIT) infra headscale policy-check

.PHONY: check
check: lint type test validate-sync
	@echo "✓ All checks passed"
