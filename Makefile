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
#   toolkit infra ansible run -p deploy-vps -e prod
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
	@echo "  make hub-pause HUB=<kubecfg>   Stop one hub reconciling (reversible; keeps its state)"
	@echo "  make hub-resume HUB=<kubecfg>  Resume a paused hub — the rollback for hub-pause"
	@echo "  make rotate-spoke-token ENV=x  Rotate spoke SA token and re-register"
	@echo ""
	@echo "Delivery (Docker Hub + gated prod promotion):"
	@echo "  make promote-prod APP=x VERSION=y  Open the prod promotion PR (ADR-046; a human still merges it)"
	@echo "  make registry-prune [DRY_RUN=1]    Prune stale sha-* image tags now, off the weekly schedule"
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
	@echo "Governance (bitácora board):"
	@echo "  make board-streams        Dry-run: what the Stream field should be, per harness/board-streams.yaml"
	@echo "  make board-streams-apply  Write the Stream field (creates it on first run)"
	@echo "  make board-streams-check  Exit 1 if any open issue is unplaced or out of date"
	@echo "  make board-parts          Dry-run: parent links the registry's parts: section implies"
	@echo "  make board-parts-apply    Add the missing parent/sub-issue links"
	@echo "  make board-sweep          Dry-run: harness/board-inprogress-sweep.yaml's Status/Priority decisions"
	@echo "  make board-sweep-apply    Write the sweep's Status/Priority changes"
	@echo "  make board-ids            Report any open issue that shares its ticket id with another"
	@echo "  make board-ids-check      Exit 1 while any open issue shares an id"
	@echo "  make board-priority       Report open issues with no Priority set (harness/priority-scale.md)"
	@echo "  make board-set ISSUE=N     Set one issue's Status/Priority/Stream by name (APPLY=1 to write)"
	@echo "  make board-priority-check Exit 1 while any open issue carries no Priority"
	@echo "  make board-deps           Report open issues named by a dependency keyword in another's body"
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

# Plan only. `APPLY=1` is what creates organizations and repositories for real —
# opt-in because the first run mutates a live forge (TOOL-035, #1076).
.PHONY: gitea-reconcile
gitea-reconcile:
	@$(TOOLKIT) services gitea reconcile --env $(or $(ENV),prod) $(if $(APPLY),--apply,)

# Plan only. `APPLY=1` revokes the token and clears its SOPS key — which OPENS AN
# OUTAGE until `make provision NODE=bee ENV=prod` mints the replacement. Both
# halves run together on purpose: the SOPS key is the mint gate, so a revoke on
# its own strands the account permanently (TOOL-035, #1076).
# `TOKEN=admin` rotates the superadmin's reconciler token instead of the bot's.
.PHONY: gitea-rotate-token
gitea-rotate-token:
	@$(TOOLKIT) services gitea rotate-token --token $(or $(TOKEN),bot) --env $(or $(ENV),prod) $(if $(APPLY),--apply,)

# Plan only. `APPLY=1` deletes ONE empty, DECLARED repository — the shells PR1
# created, which block `POST /repos/migrate` (Gitea answers 409 rather than
# filling an existing repo). Refuses a repository with content, an undeclared one,
# and one whose emptiness Gitea did not report. This is NOT a deletion path for
# the reconciler: it goes through the superadmin's basic-auth session, because
# granting either long-lived token `write:repository` would make deletion a
# standing capability (TOOL-035, #1076).
.PHONY: gitea-drop-empty
gitea-drop-empty:
	@test -n "$(REPO)" || (echo "Usage: make gitea-drop-empty REPO=owner/name [ENV=prod] [APPLY=1]" && exit 1)
	@$(TOOLKIT) services gitea drop-empty --repo $(REPO) --env $(or $(ENV),prod) $(if $(APPLY),--apply,)

# Run git against the forge with the operator credential injected into the child
# process. No workstation holds a credential for gitea.kubelab.live, and the three
# alternatives are all worse: a token in the remote URL lands in .git/config, a
# `store` helper writes it to ~/.git-credentials, and printing it to copy-paste
# puts it in a session transcript. It is `admin_password` and not a token because
# neither token may push -- measured 2026-09-04, see toolkit/features/gitea_git.py.
#
#   make gitea-git ARGS="clone https://gitea.kubelab.live/personal/resume.git"
#   make gitea-git ARGS="push origin HEAD"      # from inside the clone
.PHONY: gitea-git
gitea-git:
	@test -n "$(ARGS)" || (echo "Usage: make gitea-git ARGS='push origin HEAD' [ENV=prod]" && exit 1)
	@$(TOOLKIT) services gitea git --env $(or $(ENV),prod) -- $(ARGS)

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
#
# DIRECT=1 writes the node's MagicDNS name as the server instead, for an operator
# box already on the mesh -- there the ts-bridge tunnel is a hop that buys nothing
# and costs a running process plus its own credential. TLS still verifies: k3s puts
# the MagicDNS name in the serving cert's SANs. The fetch is SSH either way.
.PHONY: fetch-kubeconfig
fetch-kubeconfig:
	@$(TOOLKIT) infra k8s fetch-kubeconfig --env $(ENV) $(if $(DIRECT),--direct,)

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

# A scale-to-0 whose failures are swallowed cannot tell "nothing to scale" from
# "cannot reach the cluster". Measured 2026-08-23: a MIG recreate left the hub
# kubeconfig carrying a stale CA, every scale silently no-op'd, and the run only
# failed later at helm with a message naming neither cause. Asking first turns
# that into one loud error. The `|| true` below STAYS -- it is still correct for
# an empty namespace, and this target is what makes it unambiguous. (TOOL-042)
.PHONY: _require-hub-reachable
_require-hub-reachable:
	@kubectl --kubeconfig $(HUB_KUBECONFIG) version -o json --request-timeout=15s >/dev/null 2>&1 \
		|| $(MAKE) --no-print-directory _hub-unreachable

.PHONY: _hub-unreachable
_hub-unreachable:
	@echo "[ERROR] hub apiserver unreachable via $(HUB_KUBECONFIG)"
	@echo "        A recreate rotates the cluster CA, the SSH host key and the mesh address."
	@echo "        Refresh it:  make fetch-kubeconfig ENV=hub DIRECT=1"
	@exit 1

.PHONY: _deploy-argocd-helm
_deploy-argocd-helm: _require-hub-reachable
	@echo "=== Step 2/2: Installing Argo CD on the hub ==="
	@echo "--- Stopping ALL ArgoCD pods for clean upgrade (OOM mitigation) ---"
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
	@$(MAKE) --no-print-directory argocd-repoint
	@echo "✓ Argo CD deployed with OIDC. Login via https://argo.kubelab.live"

# Point prod's inbound Argo CD route at wherever gcp1 currently lives.
#
# Its own target, and called rather than inlined, because the event that
# invalidates the address is NOT a deploy: gcp1 is Spot in a MIG, so any recreate
# rotates its Tailscale IP (.21 -> .24 -> .12 -> .13 across August 2026) while the
# hub itself stays perfectly healthy. An EndpointSlice takes an IP and cannot take
# a DNS name, so the value has to be re-resolved from MagicDNS after every one.
#
# This used to be three lines buried at the end of `_deploy-argocd-helm`, and the
# EndpointSlice's comment claimed `gcp1-replace` "already tells you to run" that
# target. It never did -- see lesson-375. Repairing the route needed a ten-minute
# Helm upgrade you did not want, so the honest options were "run the wrong thing"
# or "run kubectl by hand". Hence a target that does exactly the one thing.
#
# NO `--optional` here, deliberately, and that is the difference from every other
# render-apply call: `--optional` reports success on a failed render. On a target
# whose entire purpose is repairing a dead route, a green tick over a failed
# resolve is the worst possible outcome -- prod stays down and nothing says so.
.PHONY: argocd-repoint
argocd-repoint:
	@echo "--- Pointing the prod Argo CD route at gcp1 (resolved from MagicDNS) ---"
	@$(TOOLKIT) infra k8s render-apply --env prod \
		--manifest infra/k8s/overlays/prod/argocd-endpointslice.yaml \
		--render RESOLVE_GCP1_TAILSCALE_IP=gcp1.kubelab.internal

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
		SERVER=$$($(TOOLKIT) infra argo spoke-url --env $(ENV)) && \
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
	@test -n "$(ENV)" || (echo "Usage: make unregister-spoke ENV=staging|prod HUB=<kubeconfig>" && exit 1)
	@test -n "$(HUB)" || (echo "Usage: make unregister-spoke ENV=x HUB=<kubeconfig>  # required: two hubs are live, so the hub must be named explicitly" && exit 1)
	@$(TOOLKIT) infra argo unregister-spoke --env $(ENV) --kubeconfig $(HUB) $(if $(REMOVE_SHARED_RBAC),--remove-shared-rbac,) $(if $(DRY_RUN),--dry-run,)

# Pause / resume ONE hub's reconciliation. The reversible half of a hub handover:
# unregister-spoke enforces the single-writer invariant by DELETING the retiring
# hub's credential, which also destroys the rollback; this stops the hub writing
# while it keeps everything it holds, so hub-resume is a complete rollback in one
# command. HUB is required for the same reason unregister-spoke requires it -- a
# default that silently names the wrong hub IS the defect.
# Usage: make hub-pause HUB=~/.kube/kubelab-hub-aws-config [DRY_RUN=1]
.PHONY: hub-pause
hub-pause:
	@test -n "$(HUB)" || (echo "Usage: make hub-pause HUB=<kubeconfig>  # required: two hubs are live, so the hub must be named explicitly" && exit 1)
	@$(TOOLKIT) infra argo hub-pause --kubeconfig $(HUB) $(if $(DRY_RUN),--dry-run,)

.PHONY: hub-resume
hub-resume:
	@test -n "$(HUB)" || (echo "Usage: make hub-resume HUB=<kubeconfig>  # required: two hubs are live, so the hub must be named explicitly" && exit 1)
	@$(TOOLKIT) infra argo hub-resume --kubeconfig $(HUB) $(if $(DRY_RUN),--dry-run,)

# Verify all registered spokes are reachable (from workstation, not hub)
.PHONY: check-spokes
check-spokes:
	@$(TOOLKIT) infra argo check-spokes --kubeconfig $(HUB_KUBECONFIG)

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
# Delivery (Docker Hub + gated prod promotion)
# -----------------------------------------------------------------------------
# Both targets DISPATCH A WORKFLOW; neither does the work on this machine.
#
# That is the whole design. `toolkit deployment promote --env prod` run locally
# edits the overlay in the working copy and stops — leaving a human to commit,
# branch and push it by hand, which is the manual operation the standing orders
# forbid and a production change with no PR. The workflow is what opens the
# ADR-046 promotion PR that a human then reviews and merges. Argo CD syncs after
# that merge, and never before it.
#
# They exist because the alternative is a `gh workflow run` line pasted into a
# chat window whenever someone remembers. #1585 is what that looks like over a
# quarter: prod ran kubelab-web:1.1.1 from 15 June through eleven consecutive
# releases, with every release pipeline green throughout, because dispatching by
# hand is a thing a person has to remember and eleven times nobody did.
#
# #1591 makes a web release open its own promotion PR. These targets are the
# path that stays manual on purpose: a re-promote, a rollback, `api`, or an
# unscheduled prune.
#
# GH is overridable so the tests can exercise the argument handling without
# dispatching anything. The validation below is a fast local reject, NOT the
# guard — promote-prod.yml validates authoritatively, because the dispatch can
# also arrive from somewhere this Makefile never ran.
GH ?= gh
DELIVERY_REPO ?= mlorentedev/kubelab

.PHONY: promote-prod
promote-prod: ## Open the prod promotion PR for an app at a released semver tag (ADR-046)
	@test -n "$(APP)" && test -n "$(VERSION)" || { \
		echo "Usage: make promote-prod APP=web|api VERSION=1.12.0"; exit 2; }
	@case "$(APP)" in \
		web|api) ;; \
		*) echo "Unknown APP '$(APP)' — expected web or api"; exit 2 ;; \
	esac
	@[[ "$(VERSION)" =~ ^[0-9]+\.[0-9]+\.[0-9]+$$ ]] || { \
		echo "VERSION '$(VERSION)' is not an immutable semver tag such as 1.12.0."; \
		echo "Prod ships released semver only: no leading v, no mutable alias, no sha-* staging tag."; \
		exit 2; }
	@echo "=== Dispatching prod promotion: $(APP) -> $(VERSION) ==="
	@echo "This opens a PR. Nothing deploys until a human merges it (ADR-046)."
	@$(GH) workflow run promote-prod.yml --repo $(DELIVERY_REPO) -f app=$(APP) -f version=$(VERSION)

.PHONY: registry-prune
registry-prune: ## Prune stale sha-* image tags now, off the weekly schedule (DRY_RUN=1 to list only)
	@echo "=== Dispatching registry prune$(if $(DRY_RUN), (dry run),) ==="
	@$(GH) workflow run ci-cleanup.yml --repo $(DELIVERY_REPO) -f dry_run=$(if $(DRY_RUN),true,false)

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
	#
	# BOTH branches generate first, and the else branch used to not. Two things
	# were wrong with that. The inventory is gitignored, so in a fresh worktree
	# the run simply failed — telling the operator to go run `toolkit infra
	# ansible generate` by hand, which is the raw-command habit these targets
	# exist to remove. Worse when the file DID exist: it could have been
	# generated days earlier from a different `common.yaml`, so a normal
	# provision would silently target stale inventory while the bootstrap path
	# next to it was always current. Generating is idempotent and takes under a
	# second, so there is no reason for the cheap path to be the incorrect one.
	@if [ -n "$(BOOTSTRAP)" ] || [ -n "$(TRANSPORT)" ]; then \
		echo "=== Generating inventory ($(if $(BOOTSTRAP),LAN IPs,mesh)$(if $(TRANSPORT), via $(TRANSPORT),)) ==="; \
		$(TOOLKIT) infra ansible generate --env $(_ENV) $(_BOOT) $(_TRANSPORT) && \
		$(TOOLKIT) infra ansible run -p provision-$(NODE) -e $(_ENV) $(_K) $(_TAGS) $(_CHECK) $(_EXTRA); \
		_exit=$$?; \
		echo "=== Restoring: inventory with mesh Tailscale IPs ==="; \
		$(TOOLKIT) infra ansible generate --env $(_ENV); \
		exit $$_exit; \
	else \
		$(TOOLKIT) infra ansible generate --env $(_ENV) >/dev/null && \
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

# Reclaim a node's canonical name from a dead record (#1369). The reasoning lives
# in `toolkit/features/headscale_nodes.py`; this exists because an operator
# reaching for a repair should not have to know it is spelled `toolkit infra`.
#
# APPLY=1 is required to change anything, mirroring the command's own default:
# it prints the plan otherwise. The asymmetry with CHECK=1 elsewhere is
# deliberate — CHECK opts INTO safety on a target that mutates by default, and
# this one is safe by default, so the opt-in is on the mutating side.
.PHONY: headscale-recycle-stale
headscale-recycle-stale:
	@test -n "$(NODE)" || (echo "Usage: make headscale-recycle-stale NODE=gcp1 [APPLY=1]" && exit 1)
	$(eval _APPLY := $(if $(APPLY),--apply,))
	@$(TOOLKIT) infra headscale recycle-stale --name $(NODE) $(_APPLY)

# Disk ceiling on a live node (GCP-001 AC8). Random 4K, `--direct=1`, bounded
# file, unconditional cleanup — the reasoning is in the playbook's header, where
# it stays next to the flags it justifies.
#
# NODE is required with no default and `all` is deliberately NOT supported: this
# writes to a live filesystem and reads IOPS, and a fleet-wide sweep is a
# decision to run it on production nodes you did not name.
.PHONY: benchmark-disk
benchmark-disk:
	@test -n "$(NODE)" || (echo "Usage: make benchmark-disk NODE=gcp1|vps|ace1|bee|rpi3|rpi4 [ENV=staging|prod|hub] [CHECK=1] [EXTRA='bench_size_mb=1024']" && exit 1)
	$(eval _ENV := $(or $(filter staging prod hub,$(ENV)),staging))
	$(eval _CHECK := $(if $(CHECK),--check,))
	$(eval _EXTRA := $(if $(EXTRA),--extra-vars "$(EXTRA)",))
	@$(TOOLKIT) infra ansible run -p benchmark-disk -e $(_ENV) -l $(NODE) $(_CHECK) $(_EXTRA)

.PHONY: deploy
deploy:
	@test -n "$(TARGET)" || (echo "Usage: make deploy TARGET=vps|dns|k3s|harden-nodes ENV=staging|prod [CHECK=1]" && exit 1)
	@test -n "$(ENV)" || (echo "Usage: make deploy TARGET=vps|dns|k3s|harden-nodes ENV=staging|prod [CHECK=1]" && exit 1)
	$(eval _CHECK := $(if $(CHECK),--check,))
	@$(TOOLKIT) infra ansible run -p deploy-$(TARGET) -e $(ENV) $(_CHECK)

# Run ONE node-path backup now, rather than waiting for its timer (BACKUP-044).
#
# `make backup` deploys the pipeline; this makes a backup happen. The PVC class
# has had that distinction since ADR-024 (`make backup-pvc`) and the node-path
# class did not, so an operator about to do something risky had no way to take a
# snapshot first.
#
# Starts the ship unit, which pulls capture in via `Wants=` — the real scheduled
# path, so it also posts the AC9 coverage heartbeat.
.PHONY: backup-node
backup-node:
	@test -n "$(NODE)" || (echo "Usage: make backup-node NODE=vps|rpi3|beelink|rpi4|all [ENV=prod] [CHECK=1]" && exit 1)
	$(eval _ENV := $(or $(filter staging prod,$(ENV)),prod))
	$(eval _CHECK := $(if $(CHECK),--check,))
	@if [ "$(NODE)" = "all" ]; then \
		$(TOOLKIT) infra ansible run -p backup-node -e $(_ENV) $(_CHECK); \
	else \
		$(TOOLKIT) infra ansible run -p backup-node -e $(_ENV) -l $(NODE) $(_CHECK); \
	fi

# Report, disarm, or re-arm the backup timers on a node — WITHOUT redeploying
# the pipeline to do it. `make backup-node` runs one backup and leaves the
# schedule alone, which is the gap that made AC9's teardown a hand `systemctl`
# over SSH: a demonstration that requires stopping a timer needs a supported
# way to start it again, or the teardown depends on somebody remembering.
#
# STATE is optional and omitting it REPORTS ONLY. A target an operator runs to
# look at the schedule must not change it.
.PHONY: backup-schedule
backup-schedule:
	@test -n "$(NODE)" || (echo "Usage: make backup-schedule NODE=vps|rpi3|beelink|rpi4|all [ENV=prod] [STATE=started|stopped] [CHECK=1]" && exit 1)
	$(eval _ENV := $(or $(filter staging prod,$(ENV)),prod))
	$(eval _CHECK := $(if $(CHECK),--check,))
	$(eval _STATE := $(if $(STATE),--extra-vars state=$(STATE),))
	@if [ "$(NODE)" = "all" ]; then \
		$(TOOLKIT) infra ansible run -p backup-schedule -e $(_ENV) $(_STATE) $(_CHECK); \
	else \
		$(TOOLKIT) infra ansible run -p backup-schedule -e $(_ENV) -l $(NODE) $(_STATE) $(_CHECK); \
	fi

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

# Bitácora board — the Stream field is derived from harness/board-streams.yaml (GOV-002)
# Usage: make board-streams          (dry-run)
#        make board-streams-apply    (write; creates the field on first run)
#        make board-streams-check    (exit 1 while any open issue is unplaced)
.PHONY: board-streams board-streams-apply board-streams-check
board-streams:
	@$(TOOLKIT) board streams

board-streams-apply:
	@$(TOOLKIT) board streams --apply

board-streams-check:
	@$(TOOLKIT) board streams --check

.PHONY: board-parts board-parts-apply
board-parts:
	@$(TOOLKIT) board parts

board-parts-apply:
	@$(TOOLKIT) board parts --apply

# In Progress sweep — one-time Status/Priority decision, harness/board-inprogress-sweep.yaml (GOV-005)
.PHONY: board-sweep board-sweep-apply
board-sweep:
	@$(TOOLKIT) board sweep

board-sweep-apply:
	@$(TOOLKIT) board sweep --apply

# Duplicate ticket ids among open issues (GOV-004). Not wired into CI: parallel
# sessions create issues, same reasoning as board-streams-check staying out.
.PHONY: board-ids board-ids-check
board-ids:
	@$(TOOLKIT) board ids

board-ids-check:
	@$(TOOLKIT) board ids --check

# Priority scale is harness/priority-scale.md (GOV-005).
.PHONY: board-priority board-priority-check
board-priority:
	@$(TOOLKIT) board priority

# Single-issue field set (TOOL-046). The bulk passes above cover many issues from
# a registry; this covers the one that happens most: a ticket was just filed.
# Names only -- no node ids in this file, which is the point of the ticket.
.PHONY: board-set
board-set:
	@test -n "$(ISSUE)" || (echo "Usage: make board-set ISSUE=N [STATUS=x] [PRIORITY=x] [STREAM=x] [APPLY=1]" && exit 1)
	@$(TOOLKIT) board set --issue $(ISSUE) \
		$(if $(STATUS),--status "$(STATUS)") \
		$(if $(PRIORITY),--priority "$(PRIORITY)") \
		$(if $(STREAM),--stream "$(STREAM)") \
		$(if $(APPLY),--apply)

board-priority-check:
	@$(TOOLKIT) board priority --check

# Batch-close guard (GOV-005 AC3): report-only, no --apply — this only reads
# issue bodies, it never proposes or executes a close.
.PHONY: board-deps
board-deps:
	@$(TOOLKIT) board deps

# K8s deploy — Kustomize for custom apps, Helm for third-party (ADR-021 Rev2)
# Kubeconfig derived from ENV — ignores shell $KUBECONFIG for deterministic behavior
KUBECONFIG_PATH = ~/.kube/kubelab-$(ENV)-config

# AWS Argo CD Hub — Terraform with SOPS-injected secrets
# Usage: make tf-aws-plan   (dry-run)
#        make tf-aws-apply  (create/update infrastructure)
#
# THE CLEANUP RUNS WHETHER TERRAFORM SUCCEEDS OR FAILS, and that is the whole
# reason for the `_exit` dance. Make aborts a recipe at the first failing line,
# so a `rm` on its own line never ran after a failed plan — leaving `aws.tfvars`,
# which carries `tailscale_authkey` and `headscale_api_key`, on disk indefinitely
# with nothing reporting it. A failing plan is routine: expired credentials, an
# API not enabled, a provider bump. Same `_exit=$$?` form the `provision` target
# uses to restore its inventory unconditionally.
.PHONY: tf-aws-plan tf-aws-apply tf-aws-destroy
tf-aws-plan:
	@$(POETRY) run toolkit infra terraform aws-tfvars
	@cd infra/terraform/aws && terraform init -input=false >/dev/null && \
		terraform plan -var-file=aws.tfvars; \
		_exit=$$?; rm -f aws.tfvars; exit $$_exit

tf-aws-apply:
	@$(POETRY) run toolkit infra terraform aws-tfvars
	@cd infra/terraform/aws && terraform init -input=false >/dev/null && \
		terraform apply -auto-approve -var-file=aws.tfvars; \
		_exit=$$?; rm -f aws.tfvars; \
		echo "✓ aws.tfvars cleaned (secrets in SOPS only)"; exit $$_exit

tf-aws-destroy:
	@$(POETRY) run toolkit infra terraform aws-tfvars
	@cd infra/terraform/aws && terraform init -input=false >/dev/null && \
		terraform destroy -var-file=aws.tfvars; \
		_exit=$$?; rm -f aws.tfvars; exit $$_exit

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
	@cd infra/terraform/aws && terraform init -input=false >/dev/null && \
		terraform apply -auto-approve -var-file=aws.tfvars -replace=aws_instance.argo_hub; \
		_exit=$$?; rm -f aws.tfvars; exit $$_exit
	@$(MAKE) --no-print-directory wait-node-ready NODE=aws1 ENV=hub
	@$(MAKE) --no-print-directory provision NODE=aws1 ENV=hub
	@$(MAKE) --no-print-directory deploy-argocd
	@echo "✓ aws1 replaced, provisioned and reconciling."

# GCP bootstrap — the project, its APIs and the spend guardrails.
#
# Runs ONCE, before anything billable exists, and is not part of the hub's
# lifecycle: `tf-gcp-destroy` tears the hub down routinely (preemption drills,
# machine-type changes, the AWS cutover) and must not take the project, the
# budgets or the secrets with it. Separate root, separate state.
#
# There is deliberately NO `tf-gcp-bootstrap-destroy`. The root sets
# `prevent_destroy` on the project, so destroying it is a manual, deliberate act
# rather than one keystroke next to the target that runs weekly.
#
# Unlike tf-gcp-*, this tfvars DOES carry a secret — the billing account id —
# which is why it is removed after every use rather than merely tidied away.
# `terraform init` runs first and every time, deliberately. It is idempotent and
# takes under a second once the backend exists, and without it these targets fail
# on a fresh clone with "Backend initialization required" — which is exactly the
# state anyone following the runbook from scratch is in. Measured: that is how
# the first real run of this target failed.
.PHONY: tf-gcp-bootstrap-plan tf-gcp-bootstrap-apply
tf-gcp-bootstrap-plan:
	@$(TOOLKIT) infra terraform gcp-bootstrap-tfvars
	@cd infra/terraform/gcp-bootstrap && terraform init -input=false >/dev/null && \
		terraform plan -var-file=gcp-bootstrap.tfvars; \
		_exit=$$?; rm -f gcp-bootstrap.tfvars; exit $$_exit

tf-gcp-bootstrap-apply:
	@$(TOOLKIT) infra terraform gcp-bootstrap-tfvars
	@cd infra/terraform/gcp-bootstrap && terraform init -input=false >/dev/null && \
		terraform apply -var-file=gcp-bootstrap.tfvars; \
		_exit=$$?; rm -f gcp-bootstrap.tfvars; exit $$_exit

# AC2b — prove the kill switch fires, against an expendable project.
#
# `gcp-killswitch-prove` is the whole cycle: stand up a scratch project, repoint
# the live function at it, publish a real-schema threshold message to the real
# topic, wait for billing to disappear, restore the target, tear the scratch
# down. The restore is inside the toolkit command and runs unconditionally --
# never as a later Make line, which is precisely how a cleanup gets skipped.
#
# The teardown IS conditional on nothing: `; _exit=$$?` again, because a scratch
# project left behind is a project whose id the next run collides with, and one
# that sits detached from billing looking like an incident.
.PHONY: gcp-killswitch-prove
gcp-killswitch-prove:
	@$(TOOLKIT) infra terraform killswitch-test-tfvars
	@cd infra/terraform/gcp-killswitch-test && terraform init -input=false >/dev/null && \
		terraform apply -auto-approve -var-file=killswitch-test.tfvars >/dev/null; \
		_exit=$$?; rm -f killswitch-test.tfvars; \
		if [ $$_exit -ne 0 ]; then echo "scratch project apply failed"; exit $$_exit; fi
	@_scratch=$$(cd infra/terraform/gcp-killswitch-test && terraform output -raw project_id) && \
		$(TOOLKIT) infra terraform verify-killswitch --scratch "$$_scratch"; \
		_exit=$$?; \
		$(TOOLKIT) infra terraform killswitch-test-tfvars >/dev/null && \
		( cd infra/terraform/gcp-killswitch-test && \
		  terraform destroy -auto-approve -var-file=killswitch-test.tfvars >/dev/null; \
		  rm -f killswitch-test.tfvars ); \
		exit $$_exit

# Teardown is INLINED above rather than delegated with $(MAKE), and that was
# measured: make runs sub-makes even under `-n`, so `make -n gcp-killswitch-prove`
# invoked the real teardown. A dry run that destroys something is worse than no
# dry run, because it is the command people reach for to find out what a target
# does.
#
# Kept as its own target too, for the case the cycle died so hard the inline
# teardown never ran.
.PHONY: gcp-killswitch-teardown
gcp-killswitch-teardown:
	@$(TOOLKIT) infra terraform killswitch-test-tfvars
	@cd infra/terraform/gcp-killswitch-test && \
		terraform destroy -auto-approve -var-file=killswitch-test.tfvars; \
		_exit=$$?; rm -f killswitch-test.tfvars; exit $$_exit

# GCP Argo CD Hub — Terraform driven from the SSOT, not from SOPS.
#
# The tfvars carries NO secret and that is the whole difference from tf-aws-*:
# the hub reads its credentials from Secret Manager at boot, so Terraform never
# holds one. It is still removed after every use, because a generated file left
# behind is a second declaration of the SSOT that `terraform plan` would silently
# prefer to the current one.
# Cleanup is unconditional here for a different reason than tf-aws-*: this file
# holds no secret, but a rendered tfvars left behind after a failed plan is a
# SECOND declaration of the SSOT, and the next `terraform plan` would silently
# prefer the stale one to the current config.
.PHONY: tf-gcp-plan tf-gcp-apply tf-gcp-destroy
tf-gcp-plan:
	@$(TOOLKIT) infra terraform gcp-tfvars
	@cd infra/terraform/gcp && terraform init -input=false >/dev/null && \
		terraform plan -var-file=gcp.tfvars; \
		_exit=$$?; rm -f gcp.tfvars; exit $$_exit

tf-gcp-apply:
	@$(TOOLKIT) infra terraform gcp-tfvars
	@cd infra/terraform/gcp && terraform init -input=false >/dev/null && \
		terraform apply -auto-approve -var-file=gcp.tfvars; \
		_exit=$$?; rm -f gcp.tfvars; exit $$_exit

tf-gcp-destroy:
	@$(TOOLKIT) infra terraform gcp-tfvars
	@cd infra/terraform/gcp && terraform init -input=false >/dev/null && \
		terraform destroy -var-file=gcp.tfvars; \
		_exit=$$?; rm -f gcp.tfvars; exit $$_exit

# gcp1 lifecycle — a managed instance group, which is a different animal from
# aws1's Spot request and needs none of its out-of-band cancellation. Resizing
# the MIG to 0 stops paying for the VM; resizing back to 1 builds a fresh one
# through cloud-init. aws1 never had a start/stop at all, so this is capability
# the migration adds rather than parity it restores.
#
# gcp1-replace deletes the instance and lets the MIG rebuild it. That is
# deliberately the SAME path a real preemption takes, so exercising it exercises
# the recreate contract rather than a rehearsal of it.
.PHONY: gcp1-status gcp1-start gcp1-stop gcp1-replace gcp1-destroy
gcp1-status:
	@$(TOOLKIT) infra terraform gcp-status

gcp1-start:
	@$(TOOLKIT) infra terraform gcp-resize --size 1

gcp1-stop:
	@$(TOOLKIT) infra terraform gcp-resize --size 0

gcp1-replace:
	@$(TOOLKIT) infra terraform gcp-recreate
	@$(MAKE) --no-print-directory wait-node-ready NODE=gcp1 ENV=hub
	@$(MAKE) --no-print-directory provision NODE=gcp1 ENV=hub
	# A recreate rotates gcp1's Tailscale IP, which prod's inbound route carries as
	# a literal address. Without this line the hub comes back healthy and
	# `argo.kubelab.live` stays dark -- measured 2026-08-23, lesson-375.
	@$(MAKE) --no-print-directory argocd-repoint
	@echo "✓ gcp1 recreated, provisioned, and the prod route repointed. Argo CD is installed by cloud-init."

gcp1-destroy: tf-gcp-destroy

# Block until a node can actually be provisioned: sshd answering AND cloud-init
# finished. Two conditions, not one — sshd comes up long before cloud-init has
# installed K3s and registered Tailscale. The logic lives in the playbook, not
# here, so the Makefile keeps no inline shell.
.PHONY: wait-node-ready
wait-node-ready:
	@test -n "$(NODE)" || (echo "Usage: make wait-node-ready NODE=aws1|gcp1|ace1|ace2|beelink|vps|rpi3|rpi4 [ENV=staging|prod|hub]" && exit 1)
	$(eval _ENV := $(or $(filter staging prod hub,$(ENV)),staging))
	@$(TOOLKIT) infra ansible generate --env $(_ENV) >/dev/null
	@$(TOOLKIT) infra ansible run -p wait-node-ready -e $(_ENV) -l $(NODE)

# Terraform DNS (Cloudflare) — SOPS-injected token
# THE TOKEN GOES THROUGH THE ENVIRONMENT, NEVER THROUGH argv.
#
# These targets used `-var="cloudflare_api_token=$$TOKEN"`, which puts a live
# Cloudflare API token in the process's command line -- readable by any user on
# the machine through `ps`, and captured by anything that logs command lines.
# Terraform reads `TF_VAR_<name>` from the environment, which is not in argv.
#
# Same rule the notification path already follows for the same reason
# (ANSIBLE-038 f4): a credential belongs on stdin or in the environment of the
# process that consumes it, never as an argument.
# SEC-006. Plan is safe and reversible; apply CREATES a firewall and ATTACHES it
# to the running production VPS. There is deliberately no -auto-approve on the
# apply: an allow-list mistake here is not a degraded service, it is an operator
# locked out of a host whose recovery path (Headscale) is on that same host.
# Read the plan. Hetzner's web console is the only way back in.
#
# The token goes into the child process's environment, never an argument
# (ANSIBLE-038 f4), matching tf-dns-* below. The allow-list is NOT a secret and
# comes from common.yaml via the generator, so it shows up in the diff.
.PHONY: tf-vps-firewall-plan tf-vps-firewall-apply
tf-vps-firewall-plan:
	@$(POETRY) run toolkit infra terraform vps-firewall-tfvars
	@TF_VAR_hetzner_api_token=$$($(POETRY) run toolkit secrets show hetzner.api_key --env common 2>/dev/null | tail -1) && \
		export TF_VAR_hetzner_api_token && \
		cd infra/terraform/vps-firewall && terraform init -input=false >/dev/null && \
		terraform plan

tf-vps-firewall-apply:
	@$(POETRY) run toolkit infra terraform vps-firewall-tfvars
	@TF_VAR_hetzner_api_token=$$($(POETRY) run toolkit secrets show hetzner.api_key --env common 2>/dev/null | tail -1) && \
		export TF_VAR_hetzner_api_token && \
		cd infra/terraform/vps-firewall && terraform init -input=false >/dev/null && \
		terraform apply

# The only check that can tell an APPLIED firewall from a DECLARED one. The
# token goes into pytest's environment and nowhere else -- never printed, never
# an argument, so it stays out of shell history and out of transcripts.
.PHONY: test-vps-firewall-live
test-vps-firewall-live:
	@HCLOUD_TOKEN=$$($(POETRY) run toolkit secrets show hetzner.api_key --env common 2>/dev/null | tail -1) && \
		export HCLOUD_TOKEN && \
		$(POETRY) run pytest tests/test_vps_cloud_firewall_is_attached.py -m infra -v --no-cov

.PHONY: tf-dns-plan tf-dns-apply
tf-dns-plan:
	@TF_VAR_cloudflare_api_token=$$($(POETRY) run toolkit secrets show cloudflare.api_token --env common 2>/dev/null | tail -1) && \
		export TF_VAR_cloudflare_api_token && \
		cd infra/terraform/dns && terraform init -input=false >/dev/null && \
		terraform plan -var-file=dns.tfvars

tf-dns-apply:
	@TF_VAR_cloudflare_api_token=$$($(POETRY) run toolkit secrets show cloudflare.api_token --env common 2>/dev/null | tail -1) && \
		export TF_VAR_cloudflare_api_token && \
		cd infra/terraform/dns && terraform init -input=false >/dev/null && \
		terraform apply -auto-approve -var-file=dns.tfvars

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

.PHONY: sync-vikunja
sync-vikunja: ## Idempotently reconcile Vikunja namespaces, labels, and webhooks
	@test -n "$(ENV)" || (echo "Usage: make sync-vikunja ENV=staging|prod" && exit 1)
	@$(TOOLKIT) sync vikunja --env $(ENV)

# Validate the ENV *value* against the environments that have a Vikunja, the same
# way `config-check-drift` does and for the same reason: `test -n "$(ENV)"` can
# never fail, because `ENV ?= dev` further down this file is global regardless of
# position. A bare `make vikunja-audit-users` would then audit `dev`, which has no
# Vikunja — and the audit would report an empty account list rather than an error,
# turning "I could not look" into "nobody is there". That is the exact inversion
# this command exists to prevent. #1118/#1122 shipped the weak guard twice.
#
# `$(words)` rejects the empty value and a multi-word one like ENV="staging prod",
# which `$(filter)` alone accepts and then splices unquoted into the argv.
VIKUNJA_ENVS := staging prod

# The forge is prod-identity even though the Beelink is provisioned with
# deploy_env=staging -- ADR-061's axes are independent, and "prod is an
# environment, not a location". So `prod` is the only value these targets accept,
# and the guard validates the VALUE rather than its presence: `ENV ?= dev` further
# down makes `test -n "$(ENV)"` unfailable (#1118/#1122).
GITEA_ENVS := prod

.PHONY: gitea-prune-runners
gitea-prune-runners: ## Deregister Gitea Actions runners the declaration does not name
	@{ test "$(words $(ENV))" = 1 && test -n "$(filter $(ENV),$(GITEA_ENVS))"; } || { \
		echo "Usage: make gitea-prune-runners ENV=<one of: $(GITEA_ENVS)> [APPLY=1]"; \
		echo "  Got ENV='$(ENV)'. Plan-only unless APPLY=1."; \
		exit 1; \
	}
	@$(TOOLKIT) services gitea prune-runners --env $(ENV) $(if $(APPLY),--apply,)

.PHONY: vikunja-audit-users
vikunja-audit-users: ## List Vikunja accounts, separating password signups from OIDC logins
	@{ test "$(words $(ENV))" = 1 \
	   && test -n "$(filter $(ENV),$(VIKUNJA_ENVS))"; } || { \
		echo "Usage: make vikunja-audit-users ENV=<one of: $(VIKUNJA_ENVS)>"; \
		echo "  Got ENV='$(ENV)'. Only these environments run a Vikunja; any"; \
		echo "  other value — including the repo-wide 'ENV ?= dev' default —"; \
		echo "  would report an empty account list instead of failing."; \
		exit 1; \
	}
	@$(TOOLKIT) services vikunja audit-users --env $(ENV)

.PHONY: provision-postgres-tenant
provision-postgres-tenant: ## Idempotently provision PostgreSQL tenant role and database
	@test -n "$(ENV)" || (echo "Usage: make provision-postgres-tenant ENV=staging|prod TENANT=vikunja" && exit 1)
	@$(TOOLKIT) infra k8s provision-postgres-tenant --env $(ENV) --tenant $(or $(TENANT),vikunja)

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

# BACKUP-044 AC1: does every declared node actually HAVE a backup, and how old
# is it — asked from this workstation rather than from the nodes themselves.
# Every other backup control runs on the node it checks, so it shares that
# node's fate; this one works with the homelab powered off, which is exactly
# when half the fleet cannot answer for itself.
.PHONY: backup-coverage
backup-coverage:
	@$(TOOLKIT) backup coverage --env $(or $(ENV),prod)

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

# GCP-004 AC4: an agent or operator starting fleet work should be able to see
# active alerts without opening a chat client. Prod is the monitoring of
# record (ADR-028), so that is the default here, matching `toolkit obs alerts`
# itself. `$(or $(ENV),prod)` would not do it -- ENV defaults to `dev` globally
# (below), so an unset ENV never reaches `or` empty. Same `$(filter)` idiom as
# `logs` above, needed for the same reason.
#
# Deliberately NOT `|| true`'d: an unanswered question (Grafana unreachable)
# must fail the same way a real alert would, or this becomes the next silent
# false-green.
.PHONY: alerts
alerts:
	$(eval _ENV := $(if $(filter staging prod hub,$(ENV)),$(ENV),prod))
	@$(TOOLKIT) obs alerts --env $(_ENV)

# Prove `obs015-pvc-unbound-failure` still fires, without leaving the claim
# behind afterwards (#1583). The teardown lives in the command's own `finally`,
# so there is no `drill-...-down` target here on purpose: a second target is a
# step someone has to remember, and the ten days of `ac2-drill-unbound` in
# staging are what that costs.
#
# Defaults to STAGING, unlike `alerts` above — this one CREATES a condition and
# fires a real alert, so the safe default is the environment that is not the
# monitoring of record. Same `$(filter)` idiom for the same reason (`$(or ...)`
# cannot work; see the comment on `alerts` and #1644).
#
# Expect it to take up to 45 minutes: `for: 15m` on a 15m group reading a [30m]
# window, and the claim only reaches Loki on the next disk-watcher run.
.PHONY: drill-pvc-unbound
drill-pvc-unbound:
	$(eval _ENV := $(if $(filter staging prod,$(ENV)),$(ENV),staging))
	@$(TOOLKIT) obs drill-pvc-unbound --env $(_ENV) $(if $(TIMEOUT_MINUTES),--timeout-minutes $(TIMEOUT_MINUTES),)

.PHONY: deploy-k8s
deploy-k8s: apply-secrets apply-middleware-secrets provision-postgres-tenant validate-sync
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
