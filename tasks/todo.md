# CubeLab - Roadmap

> **Goal**: Stabilize, deploy to production, extract repos, build homelab staging.
>
> **Methodology**: Kanban + XP practices (no sprints, no time-boxes)
>
> **Strategy**: Fix code → Local dev → CI → Homelab staging → Production VPS → Extract repos

---

## Methodology

### Kanban

- **WIP Limit**: 2-3 items in progress simultaneously
- **Pull-based**: Pick the next item when capacity is available
- **Priority = position** in backlog (top = most urgent)
- **No time-boxes**: No sprints, no story points
- **Blockers**: Marked with `[!]` and reference to blocking item

### XP Practices (Continuous Disciplines)

These are not tasks — they are habits that apply to ALL work:

- **TDD**: Red test → green → refactor. No separate "testing phase".
- **Small releases**: Ship functional increments frequently
- **Continuous integration**: Keep main branch deployable
- **Simple design**: Minimum viable solution first
- **Refactoring**: Improve structure while working, not as a separate task

### Symbols

| Symbol | Status |
|--------|--------|
| `[ ]` | Pending |
| `[~]` | In progress |
| `[x]` | Completed |
| `[!]` | Blocked (see reference) |

---

## Architecture Decisions (Locked)

> Decisions made 2026-02-08. Create formal ADR in vault when implemented.

### Pattern: SDK Distribution + Internal Developer Platform (IDP)

Generic toolkit published as a versioned package. Each consumer project
pins its own version and controls its upgrade timeline independently.

### Repos (under `github.com/mlorente/`)

```
cubelab-cli              → Generic Python CLI (Typer+Rich)
                           Published on GitHub Packages + PyPI
                           Reads cubelab.yaml per project
                           Command: cubelab

cubelab-platform         → Infrastructure monorepo:
                           - Platform services (Traefik, Authelia, Grafana, Gitea, n8n...)
                           - CubeLab apps (api, web, personal blog)
                           - IaC (Ansible, Terraform)
                           - Edge configs
                           Consumes: cubelab-cli

cubernautas-blog         → Cubernautas blog (separate identity)
                           Independent repo, deployed on CubeLab infra
                           Consumes: cubelab-cli

sensortool               → B2B SaaS (FastAPI/Go + Astro), portable
                           Own compose stacks, overrides for shared infra
                           Consumes: cubelab-cli

future-static-sites      → Each static site in its own repo
                           Same pattern: cubelab.yaml + cubelab-cli
```

### Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Pattern | SDK Distribution + IDP | Versioned toolkit, consumers pin versions |
| Repos | 4+ (toolkit, platform, blog, sensortool) | Each portfolio-ready, independent lifecycle |
| Config file | `cubelab.yaml` per project | Namespaced, declarative |
| Package | `cubelab-cli` → command `cubelab` | PyPI + GitHub Packages |
| Shared infra | Platform services shared, data logically isolated | One PostgreSQL, separate DBs per app |
| Portability | Compose overrides (dev=local, prod=shared) | Env vars abstract the difference |
| Blog split | cubernautas = own repo, personal blog in platform | Different identities, different lifecycles |
| Wiki | Not deployed as app — lives in toolkit as `cubelab docs` | Auto-generated from cubelab.yaml, served locally or published to `docs.cubelab.cloud` |

### Domain Strategy

| Environment | Personal site | Platform services |
|-------------|--------------|-------------------|
| Local dev | `mlorente.test` | `*.cubelab.test` |
| Staging | `web.staging.cubelab.cloud` | `*.staging.cubelab.cloud` |
| Production | `mlorente.dev` | `*.cubelab.cloud` |

Terraform DNS: two zones (`mlorente.dev` + `cubelab.cloud`)

### cubelab.yaml Schema (Reference)

```yaml
# Example for cubelab-platform
project:
  name: cubelab-platform
  type: platform           # platform | app | static-site

stacks:
  path: infra/stacks
  categories: [apps, services, edge]

apps:
  path: apps
  items:
    api: { type: go, stack: infra/stacks/apps/api }
    web: { type: astro, stack: infra/stacks/apps/web }
    blog: { type: jekyll, stack: infra/stacks/apps/blog }

environments: [dev, staging, prod]

compose:
  base_file: compose.base.yml
  env_template: "compose.{env}.yml"

config:
  values: infra/config/values
  secrets: infra/config/secrets
  env: infra/config/env

edge:
  traefik:
    templates: edge/traefik/templates
    generated: edge/traefik/generated
```

### Shared vs Per-App Infrastructure

```
Platform services (always shared):
  Traefik, Authelia, Grafana, Loki, Uptime Kuma

Stateful data (single instance, logical isolation):
  PostgreSQL → one instance, separate DB per app
  Minio → one instance, separate buckets per app

Stateless/cache (per app):
  Redis → instance per app (different eviction policies)

Task queues (per app):
  Celery broker → per app (independent scaling)
```

---

## Hardware Allocation

```
┌─────────────────────┬───────────────────────────────────┐
│  VPS Hetzner        │ Production                        │
│  162.55.57.175      │ Traefik + Apps + Services          │
├─────────────────────┼───────────────────────────────────┤
│  Beelink MiniS 8GB  │ Proxmox VE 8.x lab               │
│  cubelab-gw         │ VMs, experiments, WiFi backup mgmt │
├─────────────────────┼───────────────────────────────────┤
│  Acemagic 12GB      │ Staging (mirrors VPS)             │
│  cubelab-staging    │ Ubuntu Server 24.04 LTS + Docker   │
│                     │ Full CubeLab stack                 │
├─────────────────────┼───────────────────────────────────┤
│  RPi 4 (8GB)        │ Edge infrastructure                │
│  cubelab-edge       │ Tailscale subnet router + CoreDNS  │
│                     │ + External monitoring (Uptime Kuma) │
├─────────────────────┼───────────────────────────────────┤
│  RPi 3 (1GB)        │ Pi-hole DNS sinkhole              │
│  cubelab-dns        │ Network-wide ad blocking           │
├─────────────────────┼───────────────────────────────────┤
│  Jetson Nano (4GB)  │ Ollama + Text Polish API           │
│  cubelab-ai         │ GPU-accelerated inference           │
│                     │ Routed via Traefik on staging       │
└─────────────────────┴───────────────────────────────────┘
```

---

## Backlog

> Ordered by priority (top = most urgent). Pick items top-down.
> Respect WIP limit: max 2-3 items `[~]` simultaneously.

### Stream A: Stabilize and Deploy (current monorepo)

> Prerequisite for everything else. Flow: A1-A4 (local → CI) → Stream B (staging) → A5 (prod).
> Staging must validate the full stack before touching production.

#### A1: Verify local environment

> Blocked by: nothing (Sprint 0 completed)

- [x] **LOCAL-001**: CLI loads and responds

  ```bash
  poetry run toolkit --help
  poetry run toolkit services list
  poetry run toolkit config validate
  ```

- [x] **LOCAL-002**: Generate dev configuration

  ```bash
  ENVIRONMENT=dev poetry run toolkit config generate
  ls edge/traefik/generated/dev/
  ```

- [x] **LOCAL-003**: Start Traefik locally

  ```bash
  poetry run toolkit services up traefik
  docker ps | grep traefik
  ```

- [x] **LOCAL-004**: Start web app

  ```bash
  poetry run toolkit services up web
  ```

- [x] **LOCAL-005**: Start remaining apps (blog, api)

  ```bash
  poetry run toolkit services up blog
  poetry run toolkit services up api
  ```

- [x] **LOCAL-006**: Build tests (Go, Astro, Jekyll, MkDocs)

  ```bash
  cd apps/api/src && go build ./... && cd -
  cd apps/web/astro-site && npm ci && npm run build && cd -
  cd apps/blog/jekyll-site && bundle install && bundle exec jekyll build && cd -
  cd apps/wiki && mkdocs build && cd -
  ```

- [x] **LOCAL-007**: Toolkit code quality

  ```bash
  poetry run mypy toolkit/
  poetry run ruff check toolkit/
  poetry run black --check toolkit/
  ```

- [x] **LOCAL-008**: Create basic smoke tests

  ```bash
  mkdir -p tests
  # Minimum test: import toolkit, verify CLI commands registered
  poetry run pytest tests/ -v
  ```

**Done when**: Apps build locally, toolkit CLI works, mypy passes, >=1 test. Completed 2026-02-09

#### A2: Domain migration ✅

> Blocked by: A1 completed

- [x] **DOM-001**: Audit current domain references in the project
- [x] **DOM-002**: Update `infra/config/values/` with new domain scheme
  - dev.yaml: `*.cubelab.test` + `mlorente.test`
  - staging.yaml: `*.staging.cubelab.cloud`
  - prod.yaml: `*.cubelab.cloud` + `mlorente.dev`
- [x] **DOM-003**: Update Traefik templates (Jinja2) for new scheme
  - Templates already use variables from values.yaml (no hardcoded domains)
- [x] **DOM-004**: ~~Update `.env.*.example` files~~ — Superseded: eliminated all `.env` files, migrated to `values/*.yaml` exclusively
- [x] **DOM-005**: Update Makefile `setup-local-dns` (add `mlorente.test`)
- [x] **DOM-006**: Regenerate configs and validate
- [x] **ENV-CLEANUP**: Full `.env` removal across project (toolkit code, Ansible roles, CI workflows, documentation)

**Completed**: 2026-02-09. All domain references correct per environment.
Config model migrated from `.env` files to `values/*.yaml` + SOPS secrets.

#### A3: Full local integration

> Blocked by: A2 completed
>
> Goal: Bring up the ENTIRE stack locally, as close to prod as possible.
> Verify Traefik routes correctly to each service with local TLS.

- [x] **INT-001**: Setup local DNS and certificates

  ```bash
  make setup-local-dns       # /etc/hosts: *.cubelab.test + mlorente.test
  make setup-certs           # mkcert for all local domains
  ```

- [x] **INT-002**: Generate credentials and configuration

  ```bash
  make credentials-generate
  make config-generate
  make validate
  ```

- [x] **INT-003**: Build all images

  ```bash
  make build-dev
  ```

- [x] **INT-004**: Bring up full stack

  ```bash
  make up-dev
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  ```

- [x] **INT-005**: Verify all containers are healthy

  ```bash
  # No container in "unhealthy" or "restarting" state
  docker ps --filter "health=unhealthy" --format "{{.Names}}"
  docker ps --filter "status=restarting" --format "{{.Names}}"
  ```

- [ ] **INT-006**: HTTP smoke test for each service

  ```bash
  make smoke-test            # Target to create: curl each endpoint
  # Manual verification:
  # - https://mlorente.test (personal website)
  # - https://api.cubelab.test/health (API)
  # - https://blog.cubelab.test (blog)
  # - https://traefik.cubelab.test (dashboard)
  # - https://grafana.cubelab.test (grafana)
  # - https://portainer.cubelab.test (portainer)
  # - https://auth.cubelab.test (authelia)
  # Wiki NOT deployed — integrated in toolkit (see C1/TOOLKIT-008)
  ```

- [ ] **INT-007**: Verify Traefik routing (each domain → correct container)

  ```bash
  # Check Traefik dashboard at https://traefik.cubelab.test
  # All routers should be green
  ```

- [ ] **INT-008**: Clean teardown

  ```bash
  make down-dev
  # Verify no orphaned containers remain
  docker ps -a --filter "label=com.docker.compose.project"
  ```

**Done when**: Full stack is up (no wiki — lives in toolkit), all services respond
via HTTPS with mkcert certificates, Traefik routes correctly.
`make up-dev` → `make smoke-test` → all green.

#### A4: Push, PR and CI

> Blocked by: A3 completed (local verified end-to-end)

- [ ] **CI-001**: Push branch and create PR

  ```bash
  git push origin feature/blog-restruct
  gh pr create
  ```

- [ ] **CI-002**: Monitor CI, fix broken paths if needed

- [ ] **CI-003**: Verify Docker builds in CI

**Done when**: PR merged, CI green on main.

#### A5: Production VPS

> Blocked by: A4 completed + Stream B completed (staging validated end-to-end)

- [ ] **PROD-001**: Verify SSH access to VPS

  ```bash
  ssh mlorente-deployer@162.55.57.175 "hostname && docker --version"
  ```

- [ ] **PROD-002**: Verify/fix Terraform DNS (two zones)

  ```bash
  ENVIRONMENT=prod make config-generate
  ENVIRONMENT=prod toolkit infra terraform plan
  # Must manage: mlorente.dev + cubelab.cloud
  ```

- [ ] **PROD-003**: Deploy with Ansible

  ```bash
  ENVIRONMENT=prod toolkit infra ansible deploy
  ```

- [ ] **PROD-004**: Verify Traefik + TLS (Let's Encrypt)

  ```bash
  curl -I https://mlorente.dev
  curl -I https://api.cubelab.cloud/health
  ```

- [ ] **PROD-005**: Verify each public app/service
  - `https://mlorente.dev` (personal website)
  - `https://blog.cubelab.cloud` (cubernautas blog)
  - `https://api.cubelab.cloud` (API)
  - `https://grafana.cubelab.cloud` (monitoring)
  - Wiki not deployed — lives in toolkit (`cubelab docs serve`)

- [ ] **PROD-006**: Basic monitoring (Uptime Kuma + Loki)

**Done when**: Apps publicly accessible with valid TLS on both domains, monitoring active.

---

### Stream B: Homelab Staging Environment

> **Prerequisite for A5 (prod)**. Starts after A4 (CI green). Acemagic runs
> full stack as staging mirror of VPS. Must validate end-to-end before prod.
> RPi 4 provides network infra (Tailscale, CoreDNS, external monitoring).
> RPi 3 runs Pi-hole for LAN ad blocking. Beelink runs Proxmox for lab VMs.
>
> **ADR**: [[adr-006-tailscale-over-wireguard]] — Tailscale chosen over WireGuard
> (no port forwarding available behind NAT).
>
> **Hardware**: See vault [[hardware/_index]] for full specs and topology.

#### B0: Hardware Provisioning (manual, runbook-guided)

> User executes manually, following vault runbooks.

- [ ] **HW-001**: Install Proxmox VE 8.x on Beelink (hostname: `cubelab-gw`) → see vault [[runbooks/proxmox-setup]]
- [ ] **HW-002**: Configure WiFi dongle as backup management on Beelink
- [ ] **HW-003**: Install Ubuntu Server 24.04 LTS on Acemagic (hostname: `cubelab-staging`, user: `cubelab`)
- [ ] **HW-004**: Install Ubuntu Server 24.04 LTS on RPi 4 (hostname: `cubelab-edge`, user: `cubelab`)
- [ ] **HW-005**: Install Raspberry Pi OS Lite on RPi 3 (hostname: `cubelab-dns`, user: `cubelab`)
- [ ] **HW-006**: Setup Jetson Nano with JetPack + Docker (hostname: `cubelab-ai`)
- [ ] **HW-007**: Run Ethernet cables from router to TP-Link switch to all 5 devices
- [ ] **HW-008**: Configure DHCP reservations on home router for all 5 devices
- [ ] **HW-009**: Copy SSH keys, verify SSH access to staging + edge + dns + ai
- [ ] **HW-010**: Verify all devices can reach internet

> Runbook: vault [[runbooks/hardware-setup]]

#### B-pihole: Pi-hole on RPi 3 (can run parallel with B1)

> Quick win — useful immediately for the home network.

- [ ] **PIHOLE-001**: Install Docker on RPi 3
- [ ] **PIHOLE-002**: Deploy Pi-hole container
- [ ] **PIHOLE-003**: Configure home router to use RPi 3 as primary DNS
- [ ] **PIHOLE-004**: Verify DNS resolution and ad blocking

> Runbook: vault [[runbooks/pihole-setup]]

#### B1: Tailscale VPN Mesh

- [ ] **TS-001**: Install Tailscale on cubelab-staging, cubelab-edge, cubelab-gw, workstation
- [ ] **TS-002**: Configure cubelab-edge (RPi 4) as subnet router (`--advertise-routes`)
- [ ] **TS-003**: Approve subnet route in Tailscale admin
- [ ] **TS-004**: Record Tailscale IPs, update Ansible inventory
- [ ] **TS-005**: Configure Tailscale split DNS for `staging.cubelab.cloud` → cubelab-edge CoreDNS

> Runbook: vault [[runbooks/tailscale-setup]]

#### B2: CoreDNS on RPi 4 (parallel with B3)

- [ ] **DNS-001**: Install Docker on RPi 4
- [ ] **DNS-002**: Deploy CoreDNS container (`edge/dns-gateway/`)
- [ ] **DNS-003**: Update Corefile with cubelab-staging Tailscale IP
- [ ] **DNS-004**: Verify: `dig @<rpi4-ip> api.staging.cubelab.cloud` → cubelab-staging Tailscale IP

> Runbook: vault [[runbooks/dns-homelab]]

#### B3: Staging Configuration & Secrets

> [x] **CFG-001**: Fix `staging.yaml` (disable cloudflared, add service domains)
> [x] **CFG-002**: Create missing `compose.staging.yml` files (crowdsec, minio, github-runner)
> [x] **CFG-003**: Fix Ansible templates (paths, service lists, ports, compose naming)

- [ ] **CFG-004**: Generate staging secrets (`staging.enc.yaml` + `staging.oidc-jwks.pem`)
- [ ] **CFG-005**: Regenerate all staging configs (`ENVIRONMENT=staging toolkit config generate`)
- [ ] **CFG-006**: Validate compose files resolve for all staging services

#### B4: Acemagic Provisioning via Ansible

> Blocked by: B1 + B3

- [ ] **PROV-001**: Run `ansible-playbook setup.yml` (system_setup → docker → project_setup)
- [ ] **PROV-002**: Verify Docker, compose, network, firewall on Acemagic

#### B5: Edge + Full Deployment

> Blocked by: B2 + B4

- [ ] **EDGE-001**: Deploy Traefik on Acemagic
- [ ] **EDGE-002**: Verify Let's Encrypt TLS via DNS-01 challenge
- [ ] **EDGE-003**: Deploy Nginx error pages
- [ ] **DEPLOY-001**: Deploy Authelia + Redis (SSO prerequisite)
- [ ] **DEPLOY-002**: Deploy Apps (API, Web, Blog — pull from Docker Hub)
- [ ] **DEPLOY-003**: Deploy Observability (Grafana, Loki + Vector)
- [ ] **DEPLOY-004**: Deploy Core + Data (Portainer, CrowdSec, MinIO)
- [ ] **DEPLOY-005**: Smoke test all staging endpoints

#### B-ai: Jetson Nano — Ollama + Text Polish API

> Separate project, routed through staging Traefik via file provider.

- [ ] **AI-001**: Install Docker on Jetson Nano (JetPack environment)
- [ ] **AI-002**: Deploy Ollama container with GPU passthrough
- [ ] **AI-003**: Deploy text polish API server (browser extension backend)
- [ ] **AI-004**: Add Traefik file provider route on cubelab-staging → Jetson LAN IP
- [ ] **AI-005**: Add CoreDNS entry for `polish.staging.cubelab.cloud`
- [ ] **AI-006**: Verify end-to-end: browser extension → Traefik → Jetson → Ollama → response

#### B6: External Monitoring (RPi 4)

> Blocked by: B5

- [ ] **MON-001**: Deploy Uptime Kuma on RPi 4 (external to staging blast radius)
- [ ] **MON-002**: Configure monitors for all staging endpoints
- [ ] **MON-003**: When prod deployed (A5), add prod endpoints

#### B7: Documentation & Cleanup

- [x] **DOC-001**: Update `tasks/lessons.md` with session learnings
- [x] **DOC-002**: Rewrite Stream B in `tasks/todo.md`
- [x] **DOC-003**: Update vault hardware/_index.md (correct specs, topology, all 5 devices)
- [x] **DOC-004**: Create vault runbooks (pihole-setup, proxmox-setup)
- [x] **DOC-005**: Update vault runbooks/hardware-setup.md (all 5 devices)
- [x] **DOC-006**: Fix Ansible staging template (12GB not 16GB)
- [x] **DOC-007**: Add hardware verification lesson to tasks/lessons.md
- [ ] **DOC-008**: Create ADR-006 (Tailscale over WireGuard) in vault
- [ ] **DOC-009**: Update vault runbooks (tailscale-setup, dns-homelab, deployment) as phases complete

---

### Stream C: Repo Separation

> Prerequisite: A5 completed (prod working = safety net for repo split).
> This implements the architecture decisions above.

#### C1: Make toolkit generic

> This is the largest piece of work. Transform the toolkit from CubeLab-specific
> to generic, reading cubelab.yaml.

- [ ] **TOOLKIT-001**: Design definitive cubelab.yaml schema
  - Define what is configurable vs convention
  - Document with examples for: platform, app, static-site

- [ ] **TOOLKIT-002**: Implement cubelab.yaml loading
  - Parser with Pydantic v2 model
  - Sensible fallbacks if config is missing
  - Clear error if cubelab.yaml does not exist

- [ ] **TOOLKIT-003**: Refactor constants.py and settings.py
  - Remove hardcoded paths (PATH_STRUCTURES, SERVICES_*, etc.)
  - Everything resolves from cubelab.yaml + smart defaults

- [ ] **TOOLKIT-004**: Refactor cli/services.py
  - Discover stacks from cubelab.yaml, not from constants
  - Generic compose file resolution

- [ ] **TOOLKIT-005**: Refactor features/ (validation, generators)
  - Make generators configurable via cubelab.yaml
  - Validation reads structure from config

- [ ] **TOOLKIT-006**: Full tests for generic toolkit
  - Test with cubelab.yaml type platform
  - Test with cubelab.yaml type app
  - Test with cubelab.yaml type static-site
  - Edge cases: missing config, partial config

- [ ] **TOOLKIT-007**: Create cubelab.yaml for current monorepo
  - Verify toolkit works identically with config file

- [ ] **TOOLKIT-008**: Integrate wiki as `cubelab docs` (replaces wiki app)
  - Migrate `generator_wiki.py` to `cubelab docs` command
  - Subcommands: `generate` (static HTML), `serve` (local MkDocs), `validate` (CI)
  - Reads project structure from `cubelab.yaml`:
    - Auto-generated service catalog (apps, services, domains, versions)
    - Available commands (CLI introspection)
    - Project architecture
  - Remove wiki app from stack (Dockerfile, compose, Traefik domain)
  - Local access: `cubelab docs serve` → `http://localhost:8000`
  - Tests:
    - `cubelab docs validate` passes without errors
    - `cubelab docs generate` produces valid HTML
    - `cubelab docs serve` starts server on configurable port
    - Content reflects cubelab.yaml (correct service catalog)
  - Publication (post C2, when cubelab-cli is an independent repo):
    - CI in `cubelab-cli` generates static HTML with `cubelab docs generate`
    - Automatic deploy to GitHub Pages (`mlorente.github.io/cubelab-cli/`)
    - On VPS: Nginx/Traefik serves static HTML at `docs.cubelab.cloud`
    - Traefik route points to a lightweight container (nginx:alpine) with generated HTML
    - Option: GitHub Action in cubelab-cli deploys to VPS via SSH/rsync
    - Result: `docs.cubelab.cloud` always up-to-date with each CLI release

**Done when**: Toolkit works the same as before but reading cubelab.yaml.
Zero CubeLab-specific hardcoded logic. `cubelab docs serve` serves
auto-generated project documentation.

#### C2: Publish cubelab-cli

> Blocked by: C1 completed

- [ ] **PUB-001**: Create `cubelab-cli` repo on GitHub
  - Structure: pyproject.toml, cubelab_cli/, tests/, README
  - Move toolkit/ code to new repo

- [ ] **PUB-002**: Configure toolkit CI/CD
  - Tests on PR
  - Publish to GitHub Packages on tag
  - Publish to PyPI on tag

- [ ] **PUB-003**: First release (v0.1.0)

  ```bash
  cd cubelab-cli
  poetry version 0.1.0
  poetry publish --build
  ```

- [ ] **PUB-004**: Verify clean installation

  ```bash
  pip install cubelab-cli
  cubelab --help
  ```

**Done when**: `pip install cubelab-cli` works, `cubelab --help` responds.

#### C3: Convert monorepo → cubelab-platform

> Blocked by: C2 completed (toolkit published)

- [ ] **PLAT-001**: Update pyproject.toml
  - Remove toolkit as local code
  - Add dependency: `cubelab-cli = "^0.1.0"`

- [ ] **PLAT-002**: Clean toolkit/ directory from monorepo
  - Only cubelab.yaml remains as configuration

- [ ] **PLAT-003**: Verify everything works with external toolkit

  ```bash
  poetry install
  cubelab services list
  cubelab services up web
  ```

- [ ] **PLAT-004**: Clean repo rename references (`mlorente.dev` → `cubelab`)
  - GitHub URLs in README.md, CONTRIBUTING.md, common.yaml
  - Go module path in `apps/api/src/go.mod` + all `.go` imports
  - pyproject.toml metadata
  - Makefile/pre-commit comments
  - `toolkit/features/orchestrator.py` hardcoded health check URLs
  - Note: `mlorente.dev` as DOMAIN stays (it's the personal site domain, not the repo name)

- [ ] **PLAT-005**: Update CI/CD to use cubelab-cli as dependency

**Done when**: Monorepo works without local toolkit, consumes cubelab-cli from PyPI.

#### C4: Create sensortool

> Blocked by: C2 completed (toolkit published)
> Can be done in parallel with C3.

- [ ] **SENSOR-001**: Create `sensortool` repo on GitHub
  - Scaffold with cubelab.yaml type app
  - pyproject.toml with cubelab-cli dependency

- [ ] **SENSOR-002**: Initial structure

  ```
  sensortool/
  ├── cubelab.yaml
  ├── pyproject.toml
  ├── apps/
  │   ├── api/          # FastAPI or Go
  │   └── frontend/     # Astro
  ├── infra/stacks/
  │   └── apps/
  │       ├── api/
  │       │   ├── compose.base.yml
  │       │   ├── compose.dev.yml
  │       │   └── compose.prod.yml
  │       └── frontend/
  └── docs/
  ```

- [ ] **SENSOR-003**: Verify cubelab CLI works in the repo

  ```bash
  cubelab services list
  cubelab services up api
  ```

- [ ] **SENSOR-004**: Own CI/CD

**Done when**: Functional repo, portfolio-ready, `cubelab services up` works.

#### C5: Extract cubernautas-blog

> Blocked by: C2 completed
> Can be done in parallel with C3 and C4.

- [ ] **BLOG-001**: Create `cubernautas-blog` repo on GitHub

- [ ] **BLOG-002**: Move blog content from cubelab-platform to new repo
  - Current blog (`apps/blog/`) → `cubernautas-blog/`
  - Current stack (`infra/stacks/apps/blog/`) → adapt to new repo

- [ ] **BLOG-003**: Create personal blog in cubelab-platform
  - Replace the blog that left with a personal one

- [ ] **BLOG-004**: cubelab.yaml + own CI/CD

- [ ] **BLOG-005**: Verify deploy on CubeLab infra

**Done when**: Cubernautas is an independent repo, personal blog in platform.

---

### Stream D: Data and Observability

> Only implement when an app needs it. If no app needs a database, defer.

#### D1: Persistence Layer

- [ ] **DATA-001**: Deploy PostgreSQL 16 (one instance, DBs per app)
- [ ] **DATA-002**: Create databases with per-app isolation
- [ ] **DATA-003**: Deploy Redis 7 (instance per app that needs it)
- [ ] **DATA-004**: Deploy MinIO (if object storage is needed)
- [ ] **DATA-005**: Configure pg_dump daily backup
- [ ] **DATA-006**: Test backup/restore cycle

#### D2: Observability

- [ ] **OBS-001**: Grafana working on staging + prod
- [ ] **OBS-002**: Loki receiving logs from all containers
- [ ] **OBS-003**: 5 basic dashboards (health, requests, errors, resources, uptime)
- [ ] **OBS-004**: Basic alerts (container down, high error rate)

---

### Stream E: Backlog (unprioritized)

> Items without defined order. Prioritize when capacity or need arises.

**Tier 1: Likely**

- [ ] Workers deployment: compose files in `infra/stacks/apps/workers/`
- [ ] Workers Phase 2: Media processing (FFmpeg, WebP)
- [ ] Test coverage: 30%+ on toolkit core modules
- [ ] Terraform DNS: Generate `services.json` from `common.yaml`
- [ ] Consolidate youtube-toolkit → `apps/workers/youtube/`
- [ ] SOPS alignment: Align with age keys from dotfiles

**Tier 2: Possible**

- [ ] ClawdBot: Telegram bot (framework, approval workflow)
- [ ] K3s Learning Lab: K3s on Proxmox
- [ ] ArgoCD: GitOps for staging
- [ ] Authelia expand: OIDC for more services
- [ ] Workers Phase 3: AI (embeddings, RAG, summarization)

**Tier 3: Ideas (no commitment)**

- [ ] K3s multi-arch cluster with RPi #2
- [ ] Helm charts for all apps
- [ ] Workers Phase 4-5 (data aggregator, system maintenance)
- [ ] Newsletter (Cubernautas) setup

---

## Best Practices Reference

### Compose File Pattern

```bash
docker compose -f compose.base.yml -f compose.dev.yml up -d

# compose.base.yml: image, healthcheck, networks, volumes
# compose.dev.yml: hot reload, debug, local ports
# compose.staging.yml: mirrors prod, limited resources
# compose.prod.yml: resource limits, logging, replicas
```

### Service Categories

| Category | Purpose | Services |
|----------|---------|----------|
| **core** | Essential platform | gitea, portainer, n8n, vaultwarden |
| **observability** | Monitoring/logging | grafana, loki, uptime |
| **security** | Auth/protection | authelia, crowdsec |
| **data** | Storage/docs | minio, docmost |
| **automation** | CI/workflows | github-runner, kestra |
| **ai** | ML/AI | ollama, webui |
| **misc** | Productivity | calcom, immich |

### Environment Strategy

```
dev      → Local (hot reload, debug, mkcert certs)
staging  → Acemagic homelab (mirrors prod, Tailscale access)
prod     → Hetzner VPS (public, Let's Encrypt TLS)
```

### CLI Command Reference

```bash
cubelab services up <name>       # Start app or service
cubelab services down <name>     # Stop
cubelab services logs <name>     # View logs
cubelab services list            # List available
cubelab config generate          # Generate configs from templates
cubelab config validate          # Validate configs
cubelab credentials generate     # Generate credentials
cubelab infra ansible deploy     # Deploy with Ansible
cubelab infra terraform plan     # Terraform plan
cubelab deployment deploy        # Full deployment pipeline
cubelab dashboard                # Terminal dashboard
cubelab tools certs generate     # Generate local certs
cubelab docs serve               # Serve project documentation locally
cubelab docs generate            # Generate static HTML docs
```

---

## Completed

### 2026-02-10

- [x] Stream B Phase 0: Documentation updates for homelab architecture
- [x] Vault hardware/_index.md rewritten: correct specs (12GB Acemagic, 8GB RPi 4, 1GB RPi 3, 8GB Beelink, 4GB Jetson), topology, resource budget
- [x] SD card assignments: 256GB Jetson (AI models), 128GB RPi 4 (edge), 64GB RPi 3 (Pi-hole)
- [x] Vault runbooks/hardware-setup.md rewritten: all 5 devices, DHCP table, Proxmox + Pi-hole + Jetson sections
- [x] Vault runbooks/pihole-setup.md created: Pi-hole Docker on RPi 3, router DNS config
- [x] Vault runbooks/proxmox-setup.md created: Proxmox VE 8.x on Beelink, WiFi backup mgmt, bridge networking
- [x] Ansible staging template fixed: 16GB → 12GB, MiniPC B → Acemagic
- [x] Hardware verification lesson added to tasks/lessons.md
- [x] Stream B backlog revised: B0 expanded to 10 tasks (5 devices), added B-pihole and B-ai phases

### 2026-02-09

- [x] A1 completed: local environment verified (CLI, builds, tests, code quality)
- [x] Astro config fix: `PUBLIC_ALLOWED_HOSTS` undefined fallback
- [x] MkDocs fixes: YAML indentation, deprecated emoji extension, corrupt UTF-8 in footer
- [x] Black formatting fix on generator_traefik.py
- [x] Smoke tests: 22 tests passing, 26% coverage baseline
- [x] Docker permission fixes: root-owned .vite/, .astro/, .jekyll-cache/
- [x] Dev compose user fix: added `user: "${UID:-1000}:${GID:-1000}"` to web and blog
- [x] Created .dockerignore for web app
- [x] Domain strategy defined: mlorente.dev (personal) + cubelab.cloud (platform)
- [x] Wiki decision: removed as deployed app, will integrate as `cubelab docs` in toolkit (C1/TOOLKIT-008)
- [x] Roadmap restructured: A1→A5 (added domain migration + local integration phases)
- [x] A2 completed: domain migration across all values/*.yaml files
- [x] Full .env elimination: deleted physical files, cleaned toolkit code, Ansible roles, CI workflows
- [x] Documentation updated: AGENTS.md rewrite, CLAUDE.md, 7 docs/README files migrated to values/*.yaml references
- [x] Ansible roles modernized: compose overlay pattern (compose.base.yml + compose.{env}.yml)

### 2026-02-08

- [x] Architecture decisions: SDK Distribution + IDP pattern
- [x] Define repos: cubelab-cli, cubelab-platform, sensortool, cubernautas-blog
- [x] Methodology change: Kanban + XP (no sprints)
- [x] Define cubelab.yaml schema
- [x] Decide shared vs per-app services
- [x] Sprint 0A completed: 5 FIX tickets (compose filenames, edge CLI, constants, pre-push, infra/compose refs)
- [x] Sprint 0B completed: 11 ALIGN tickets (CLAUDE.md, README, TOOLKIT, CONTRIBUTING, workflows)
- [x] Sprint 0C completed: Pre-commit hooks (18/18), successful commit
- [x] Pre-commit fixes: mypy (44 errors), ruff (30+ errors), yamllint, hadolint, gitleaks, black
- [x] Commit: `refactor: restructure project architecture and align toolkit`

### 2026-02-05

- [x] Full project audit (structure, toolkit, CI/CD, docs, infra)
- [x] Identify 10 code bugs
- [x] Replan roadmap

### 2026-02-04

- [x] Merge BACKLOG.md and todo.md into single file
- [x] Define hardware architecture
- [x] Refine hybrid architecture (VPS WireGuard Hub)

### 2026-02-03

- [x] Deep project analysis
- [x] Create initial execution plan

### Feature Branch (Pre-commit)

- [x] Reorganize infrastructure to `infra/stacks/`
- [x] Translate blog to Spanish
- [x] Consolidate edge services
- [x] Add new services (Gitea, Authelia, CrowdSec, etc.)
- [x] Workers Phase 1: YouTube toolkit
- [x] CLI Architecture Audit

---

*Last updated: 2026-02-10*
*Next action: Finish A3 (INT-006/007/008), then B0 (hardware provisioning)*
