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
│  RPi 4 (8GB)        │ Network gateway + AI agents        │
│  cubelab-edge       │ Bridge/NAT (USB ETH↑ built-in↓)   │
│                     │ Pi-hole + CoreDNS + Tailscale      │
│                     │ OpenClaw + PicoClaw                │
├─────────────────────┼───────────────────────────────────┤
│  Acemagic 12GB      │ Staging (mirrors VPS)             │
│  cubelab-staging    │ Ubuntu Server 24.04 LTS + Docker   │
│                     │ Full CubeLab stack                 │
├─────────────────────┼───────────────────────────────────┤
│  Beelink MiniS 8GB  │ Proxmox VE 8.x lab               │
│  cubelab-gw         │ VMs, experiments                   │
├─────────────────────┼───────────────────────────────────┤
│  RPi 3 (1GB)        │ External monitor (independent)    │
│  cubelab-monitor    │ Uptime Kuma (probes VPS+homelab)   │
├─────────────────────┼───────────────────────────────────┤
│  Jetson Nano #1     │ Pollex (llama.cpp + Qwen 2.5)     │
│  cubelab-ai         │ GPU inference, text polish API     │
├─────────────────────┼───────────────────────────────────┤
│  Jetson Nano #2     │ Spare (backup for #1)             │
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

- [x] **INT-006**: HTTP smoke test for each service

  ```bash
  # All 11 endpoints verified:
  # 200: mlorente.test, api.cubelab.test/health, blog.cubelab.test, auth.cubelab.test
  #      minio.cubelab.test/minio/health/live, console.minio.cubelab.test
  # 302: traefik.cubelab.test, grafana.cubelab.test, portainer.cubelab.test,
  #      status.cubelab.test, gitea.cubelab.test (→ Authelia SSO, expected)
  ```

- [x] **INT-007**: Verify Traefik routing (each domain → correct container)

  ```bash
  # All routers green in Traefik dashboard
  # Fixed: portainer had cubelab.cloud instead of cubelab.test (duplicate YAML key bug in dev.yaml)
  ```

- [x] **INT-008**: Clean teardown

  ```bash
  toolkit services down --all   # New --all flag implemented
  # Only buildx_buildkit_multiarch0 remains (Docker Buildx builder, not CubeLab)
  ```

**Completed**: 2026-02-14. Full stack up, 11 endpoints verified via HTTPS,
Traefik routes correctly, clean teardown with `toolkit services down --all`.

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
> full stack as staging mirror of VPS. RPi 4 is the network gateway (bridge/NAT,
> Pi-hole, CoreDNS, Tailscale) and hosts AI agents (OpenClaw, PicoClaw).
> RPi 3 runs external monitoring (Uptime Kuma) independently. Beelink runs Proxmox for lab VMs.
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
- [ ] **HW-005**: Install Raspberry Pi OS Lite on RPi 3 (hostname: `cubelab-monitor`, user: `cubelab`)
- [ ] **HW-006**: Setup Jetson Nano #1 with JetPack + Docker (hostname: `cubelab-ai`)
- [ ] **HW-007**: Connect USB 3.0 Ethernet adapter to RPi 4 (uplink to router)
- [ ] **HW-008**: Run Ethernet from RPi 4 built-in port to TP-Link switch (downlink)
- [ ] **HW-009**: Connect RPi 3 directly to home router (independent path, not through switch)
- [ ] **HW-010**: Connect Acemagic, Beelink, Jetson to TP-Link switch
- [ ] **HW-011**: Configure DHCP reservations on home router for all devices
- [ ] **HW-012**: Configure RPi 4 as bridge/NAT (iptables/nftables, IP forwarding)
- [ ] **HW-013**: Copy SSH keys, verify SSH access to staging + edge + monitor + ai
- [ ] **HW-014**: Verify all devices can reach internet via RPi 4 bridge

> Runbook: vault [[runbooks/hardware-setup]]

#### B-pihole: Pi-hole on RPi 4 (can run parallel with B1)

> Pi-hole runs on RPi 4 (gateway node) alongside CoreDNS. All DNS consolidated.

- [ ] **PIHOLE-001**: Deploy Pi-hole container on RPi 4
- [ ] **PIHOLE-002**: Configure Pi-hole upstream DNS + blocklists
- [ ] **PIHOLE-003**: Configure home router to use RPi 4 as primary DNS
- [ ] **PIHOLE-004**: Verify DNS resolution and ad blocking from all homelab devices

> Runbook: vault [[runbooks/pihole-setup]]

#### B1: Tailscale VPN Mesh

- [ ] **TS-001**: Install Tailscale on cubelab-staging, cubelab-edge, cubelab-gw, workstation
- [ ] **TS-002**: Configure cubelab-edge (RPi 4) as subnet router (`--advertise-routes`)
- [ ] **TS-003**: Approve subnet route in Tailscale admin
- [ ] **TS-004**: Record Tailscale IPs, update Ansible inventory
- [ ] **TS-005**: Configure Tailscale split DNS for `staging.cubelab.cloud` → cubelab-edge CoreDNS

> Runbook: vault [[runbooks/tailscale-setup]]

#### B2: CoreDNS on RPi 4 (parallel with B3)

> CoreDNS runs alongside Pi-hole on RPi 4 gateway. Docker already installed in B-pihole.

- [ ] **DNS-001**: Deploy CoreDNS container on RPi 4 (`edge/dns-gateway/`)
- [ ] **DNS-002**: Update Corefile with cubelab-staging Tailscale IP
- [ ] **DNS-003**: Verify: `dig @<rpi4-ip> api.staging.cubelab.cloud` → cubelab-staging Tailscale IP

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

#### B-ai: Jetson Nano — Pollex (llama.cpp)

> Separate project ([[../../pollex/_index|Pollex]]), routed through staging Traefik via file provider.
> Qwen 2.5 1.5B Q4_0, full GPU offload on Jetson Nano Maxwell GPU.

- [ ] **AI-001**: Install Docker on Jetson Nano (JetPack environment)
- [ ] **AI-002**: Deploy llama-server with Qwen 2.5 1.5B Q4_0 model (GPU offload `-ngl 999`)
- [ ] **AI-003**: Deploy Pollex Go API (browser extension backend, port 8090)
- [ ] **AI-004**: Add Traefik file provider route on cubelab-staging → Jetson LAN IP
- [ ] **AI-005**: Add CoreDNS entry for `polish.staging.cubelab.cloud`
- [ ] **AI-006**: Verify end-to-end: browser extension → Traefik → Pollex API → llama-server → response

#### B6: External Monitoring (RPi 3)

> Blocked by: B5. RPi 3 connects directly to router (independent internet),
> outside RPi 4 blast radius. Monitors both homelab and VPS.

- [ ] **MON-001**: Install Docker on RPi 3 (`cubelab-monitor`)
- [ ] **MON-002**: Install Tailscale on RPi 3 (access internal services for probes)
- [ ] **MON-003**: Deploy Uptime Kuma on RPi 3
- [ ] **MON-004**: Configure monitors for all staging endpoints (via Tailscale)
- [ ] **MON-005**: Configure alerts (Telegram/email)
- [ ] **MON-006**: When prod deployed (A5), add VPS endpoints

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

#### D2: Observability — Logs (already partially deployed)

> Grafana + Loki already exist in stacks. This phase ensures they work end-to-end.

- [ ] **OBS-001**: Grafana working on staging + prod
- [ ] **OBS-002**: Loki receiving logs from all containers (via Vector)

#### D3: Observability — Metrics

> **ADR**: [[adr-009-prometheus-metrics-stack]]
>
> Blocked by: B5 (staging operational). Grafana must be working (OBS-001).
> Adds host metrics, container metrics, and HTTP request metrics with historical storage.

- [ ] **MET-001**: Create Prometheus stack (`infra/stacks/services/observability/prometheus/`)
  - `compose.base.yml`: Prometheus server
  - `prometheus.yml`: scrape config (Node Exporter, cAdvisor, Traefik targets)
  - Retention: 15 days
  - `compose.dev.yml`, `compose.staging.yml`, `compose.prod.yml`

- [ ] **MET-002**: Deploy Node Exporter
  - Add to Prometheus stack (or separate lightweight compose)
  - Bind-mount `/proc`, `/sys`, `/` read-only
  - Verify: `curl localhost:9100/metrics` returns host metrics

- [ ] **MET-003**: Deploy cAdvisor
  - Add to Prometheus stack
  - Bind-mount Docker socket (read-only) + `/sys`, `/var/lib/docker`
  - Verify: `curl localhost:8080/metrics` returns per-container metrics

- [ ] **MET-004**: Enable Traefik Prometheus metrics
  - Add `--metrics.prometheus=true` to Traefik static config
  - Add `--entryPoints.metrics.address=:8082` (internal only, not exposed via Traefik routes)
  - Verify: `curl localhost:8082/metrics` returns request metrics

- [ ] **MET-005**: Configure Prometheus scrape targets
  ```yaml
  # prometheus.yml
  scrape_configs:
    - job_name: node-exporter
      static_configs:
        - targets: ['node-exporter:9100']
    - job_name: cadvisor
      static_configs:
        - targets: ['cadvisor:8080']
    - job_name: traefik
      static_configs:
        - targets: ['traefik:8082']
  ```

- [ ] **MET-006**: Add Prometheus datasource to Grafana
  - Grafana provisioning: add Prometheus alongside Loki
  - Verify: Grafana → Explore → Prometheus → `up` query returns targets

- [ ] **MET-007**: Import Grafana dashboards
  - Node Exporter Full (ID: 1860) — host resources
  - Docker & cAdvisor (ID: 893) — container resources
  - Traefik (ID: 17346) — HTTP traffic
  - Verify: all 3 dashboards populate with real data

- [ ] **MET-008**: Create custom CubeLab overview dashboard
  - Panel 1: Host CPU/RAM/Disk per node (Node Exporter)
  - Panel 2: Top 10 containers by RAM (cAdvisor)
  - Panel 3: Requests/s per service (Traefik)
  - Panel 4: Error rate (4xx/5xx) per service (Traefik)
  - Panel 5: Request latency p95 per service (Traefik)

#### D4: Alerting

> Blocked by: D3 completed (metrics flowing)

- [ ] **ALERT-001**: Configure Grafana alerting (or Alertmanager)
  - Alert: container down (up == 0) for > 2 min
  - Alert: host CPU > 85% for > 5 min
  - Alert: host disk > 90%
  - Alert: HTTP error rate (5xx) > 5% for > 3 min
  - Alert: container restart loop (restart count > 3 in 10 min)

- [ ] **ALERT-002**: Notification channel
  - Slack webhook (via n8n or direct Grafana Slack integration)
  - Verify: trigger a test alert → Slack notification received

**Done when**: Grafana shows real-time and historical metrics for all hosts, containers,
and HTTP traffic. 3 imported dashboards + 1 custom overview dashboard. Alerts firing to Slack.

---

### Stream F: Agent-Delegated Task Management

> **ADR**: [[adr-007-vikunja-n8n-openclaw-task-delegation]]
>
> Replaces Google Keep with self-hosted task management (Vikunja) + AI agent delegation
> via n8n orchestration + OpenClaw execution. Human-in-the-loop at all checkpoints.
>
> **Prerequisite**: Stream B completed (staging environment operational).
> n8n must be deployed before F2. Can start F1 as soon as staging is up.

#### F1: Vikunja Deployment

> Blocked by: B5 (staging operational)

- [ ] **VIK-001**: Create Vikunja stack (`infra/stacks/services/core/vikunja/`)
  - `compose.base.yml`: Vikunja + PostgreSQL (or shared instance)
  - `compose.dev.yml`, `compose.staging.yml`, `compose.prod.yml`

- [ ] **VIK-002**: Add Vikunja config to `infra/config/values/common.yaml`
  - Domain: `tasks.cubelab.test` / `tasks.staging.cubelab.cloud` / `tasks.cubelab.cloud`
  - Resource limits, OIDC config (Authelia), SMTP for notifications

- [ ] **VIK-003**: Add Traefik route for Vikunja
  - Update templates or add to generated config
  - Authelia middleware for SSO login

- [ ] **VIK-004**: Deploy and verify Vikunja locally
  ```bash
  toolkit services up vikunja
  curl -I https://tasks.cubelab.test
  ```

- [ ] **VIK-005**: Configure initial project structure in Vikunja
  - Projects: `cubelab/infra`, `cubelab/apps`, `trabajo`, `personal`
  - Labels: `agent:delegable`, `priority:high`, `priority:low`, `checkpoint:per-subtask`, `checkpoint:final-only`
  - Custom states: `pending`, `agent_working`, `checkpoint`, `approved`, `done`

- [ ] **VIK-006**: Configure Vikunja webhooks
  - Webhook on task create/update → n8n endpoint
  - Filter: only fire for tasks with `agent:delegable` label

**Done when**: Vikunja accessible via HTTPS, SSO via Authelia, projects and labels configured,
webhooks pointing to n8n endpoint.

#### F2: n8n Agent Pipeline Workflow

> Blocked by: F1 + n8n deployed (n8n is already in service catalog as core service)

- [ ] **N8N-001**: Design n8n workflow: "Agent Task Pipeline"
  - Webhook trigger (Vikunja task event)
  - Validate `agent:delegable` label
  - Extract YAML agent context from task description
  - Error handling: malformed YAML → Slack notification to user

- [ ] **N8N-002**: Implement decomposition phase
  - Call OpenClaw API: "Decompose this task"
  - Receive proposed subtasks
  - Create subtasks in Vikunja via API
  - Slack notification: "Agent proposes N subtasks. Approve?"
  - Wait for callback (Slack button or Vikunja state change)

- [ ] **N8N-003**: Implement execution loop
  - For each subtask:
    - Call OpenClaw API: execute subtask with agent context
    - On completion: update Vikunja subtask state
    - At checkpoint: pause workflow, notify Slack with artifacts (PR URLs, diffs)
    - Wait for human approval (callback from Slack or Vikunja)
    - On reject: notify agent, allow revision
  - Timeout: if no agent progress in X minutes → pause + Slack alert

- [ ] **N8N-004**: Implement completion phase
  - All subtasks approved → mark parent task as Done in Vikunja
  - Slack summary: "Task completed. N subtasks, M checkpoints, T tokens used."
  - Audit log entry (tokens consumed, duration, artifacts)

- [ ] **N8N-005**: Slack interactive messages
  - Approve/Reject buttons on checkpoint notifications
  - Comment field for feedback to agent
  - Thread grouping: one Slack thread per parent task

**Done when**: End-to-end workflow works in n8n — task creation triggers decomposition,
agent executes with checkpoints, human approves via Slack, task marked done.

#### F3: Agent Deployment on RPi 4

> Blocked by: B0 (RPi 4 provisioned as gateway). Can run parallel with F1.
> Agents run on RPi 4 (`cubelab-edge`, 8GB) — no GPU needed, uses external LLM APIs.

- [ ] **CLAW-001**: Evaluate OpenClaw + PicoClaw deployment requirements
  - OpenClaw: Node.js, npm install, API documentation
  - PicoClaw: Go binary, minimal config, Docker support
  - LLM providers: DeepSeek, OpenRouter (no Anthropic API key needed)

- [ ] **CLAW-002**: Deploy OpenClaw on RPi 4
  - Docker or native Node.js install
  - Configure LLM backend (DeepSeek API or OpenRouter)
  - Configure integrations (email, calendar, GitHub, Telegram, etc.)

- [ ] **CLAW-003**: Deploy PicoClaw on RPi 4
  - Docker container or Go binary
  - Configure LLM backend (DeepSeek)
  - Configure chat integrations (Telegram, Discord)
  - Configure scheduled tasks (cron expressions)

- [ ] **CLAW-004**: Configure n8n → OpenClaw pipeline
  - n8n (Acemagic) calls OpenClaw API (RPi 4) over LAN/Tailscale
  - Verify webhook connectivity

- [ ] **CLAW-005**: Configure multi-repo agent access
  - Git credential helper for agent containers
  - Per-repo access list (user configurable via Vikunja task context)
  - Security: agents NEVER get access to SOPS keys, production credentials, or infra repos unless explicitly allowed

- [ ] **CLAW-006**: Test agent execution in isolation
  - Create test task: "Add a README to test repo"
  - Verify: agent clones repo, creates branch, makes changes, pushes PR
  - Verify: agent cannot access repos not in allowed list

**Done when**: OpenClaw + PicoClaw running on RPi 4, accessible via LAN/Tailscale,
agents use DeepSeek/OpenRouter for LLM, isolation verified.

#### F5: Agent Persistent Memory

> Blocked by: F3 (agents deployed). Agents must retain context across sessions.
> Without persistent memory, agents forget previous work, repeat mistakes,
> and lose accumulated knowledge about projects and preferences.

- [ ] **MEM-001**: Design memory architecture (MEMORY.md + QMD hybrid)
  - **Decision**: Same pattern as Claude Code — proven in daily use
  - MEMORY.md: flat file loaded at session start (conventions, decisions, preferences, ~200 lines)
  - QMD: structured observation database (searchable by date/type/project/keyword)
  - Evaluate QMD options for self-hosted: sqlite-based, file-based JSON, or lightweight DB
  - Must run on RPi 4 (arm64, 8GB) — no heavy dependencies

- [ ] **MEM-002**: Implement chosen memory system
  - Agent reads memory on startup / before each task
  - Agent writes learnings after task completion
  - Memory includes: project conventions, past decisions, error patterns, user preferences
  - Timestamped entries for freshness tracking

- [ ] **MEM-003**: Define memory lifecycle
  - What to remember: confirmed patterns, architectural decisions, user preferences, bug fixes
  - What to forget: session-specific context, speculative conclusions
  - Pruning strategy: stale entries after N days without reference
  - Memory budget: max file size or entry count to prevent bloat

- [ ] **MEM-004**: Integration with agent workflows
  - OpenClaw: pre-task memory load, post-task memory write
  - PicoClaw: persistent context across chat sessions
  - n8n: pass relevant memory context in task execution payload

- [ ] **MEM-005**: Test memory persistence
  - Agent completes task A → learns pattern → completes task B using that knowledge
  - Agent restart → memory survives
  - Verify: no hallucinated memories, no stale data causing bad decisions

**Done when**: Agents retain knowledge across sessions, reference past decisions,
and avoid repeating mistakes. Memory is searchable and prunable.

#### F4: Integration Testing

> Blocked by: F2 + F3

- [ ] **INT-F01**: End-to-end test: simple single-subtask flow
  - Create task in Vikunja with `agent:delegable`
  - Verify: n8n triggers → OpenClaw runs → Slack notification → approve → done

- [ ] **INT-F02**: End-to-end test: multi-subtask with checkpoints
  - Task with `checkpoints: per-subtask`
  - Verify: each subtask pauses for approval before next starts

- [ ] **INT-F03**: End-to-end test: rejection and revision
  - Reject a checkpoint → verify agent receives feedback
  - Agent revises → new checkpoint → approve

- [ ] **INT-F04**: End-to-end test: timeout handling
  - Simulate agent hang → verify timeout triggers Slack alert

- [ ] **INT-F05**: Verify non-delegable tasks are unaffected
  - Create task WITHOUT `agent:delegable` label
  - Verify: no n8n workflow triggered, task behaves as normal Vikunja task

- [ ] **INT-F06**: Multi-repo test
  - Task targeting repo outside cubelab (e.g., sensortool)
  - Verify: agent accesses correct repo with correct credentials

**Done when**: All integration tests pass. Delegable and non-delegable tasks coexist.
Slack communication bidirectional. Timeout and rejection flows work.

---

### Stream G: Self-Hosted Knowledge Base (Obsidian → Web)

> **ADR**: [[adr-008-quartz-obsidian-knowledge-base]]
>
> Read-only web viewer for the Obsidian vault using Quartz (static site generator).
> Synced via Git cron (5 min). Defense-in-depth: Authelia (access) + Quartz filtering (content).
>
> **Prerequisite**: Stream B completed (staging operational).
> Independent of Stream F. Small scope — can be done in a few sessions.

- [ ] **KB-001**: Create Knowledge Base stack (`infra/stacks/services/core/knowledge-base/`)
  - `compose.base.yml`: nginx:alpine serving Quartz HTML output
  - Sidecar/init container: git clone + `npx quartz build`
  - Cron script: `git pull` + rebuild every 5 min (only if changes detected)
  - `compose.dev.yml`, `compose.staging.yml`, `compose.prod.yml`

- [ ] **KB-002**: Add config to `infra/config/values/common.yaml`
  - Domain: `kb.cubelab.test` / `kb.staging.cubelab.cloud` / `kb.cubelab.cloud`
  - Git repo URL for vault
  - Quartz config: published folders/tags whitelist

- [ ] **KB-003**: Configure Quartz content filtering
  - Define folder whitelist (e.g., `10_projects/cubelab/`, `20_areas/engineering/`)
  - Exclude sensitive folders (credentials, personal, private notes)
  - Tag-based filter: only notes tagged `public` or in approved folders
  - Verify: build output contains ZERO sensitive notes

- [ ] **KB-004**: Add Traefik route with Authelia middleware
  - `kb.cubelab.test` → knowledge-base container
  - Authelia SSO required (no anonymous access)

- [ ] **KB-005**: Deploy and verify locally
  ```bash
  toolkit services up knowledge-base
  # Should redirect to Authelia login first
  curl -I https://kb.cubelab.test
  # After auth: vault content visible, graph view works, wikilinks resolve
  ```

- [ ] **KB-006**: Verify sync cycle
  - Edit a note in Obsidian → push to Git
  - Wait 5 min (or trigger manual rebuild)
  - Verify: change appears on `kb.cubelab.test`

- [ ] **KB-007**: Verify security layers
  - Layer 1: unauthenticated request → Authelia redirect (no content leaked)
  - Layer 2: inspect built HTML → no sensitive folders/notes present
  - Verify excluded content is not in search index either

**Done when**: Vault accessible at `kb.cubelab.test` behind Authelia, auto-syncs from Git,
graph view and wikilinks work, sensitive content excluded at build time AND access-controlled.

---

### Stream H: Agent Workforce (24/7 Autonomous Operations)

> **ADR**: Pending — create when designing.
>
> **Prerequisite**: Stream F completed (agents deployed + task management operational).
> Builds on F's infrastructure to create self-sustaining agent loops that
> minimize human intervention for low-risk, repeatable tasks.
>
> **Design decisions (open — resolve in ADR):**
> 1. Budget model: Claude MAX (80% weekly cap) + DeepSeek (bulk cheap tasks) + local Pollex (free, text-only)
> 2. Task catalog: which tasks are delegable, risk tier per task type
> 3. Autonomy levels: Level 2 (checkpoint) vs Level 3 (autonomous with guardrails) per task tier

#### H1: LLM Budget & Routing Strategy

> Define which LLM handles which task type based on cost, quality, and latency.

- [ ] **BUD-001**: Map task types to LLM tiers
  - **Tier 1 (free/local)**: Pollex on Jetson — text polish, spelling, short rewrites
  - **Tier 2 (cheap)**: DeepSeek API — triaje, log analysis, scraping, data transforms, content drafts
  - **Tier 3 (premium)**: Claude via MAX plan — architecture review, complex code, PR reviews
- [ ] **BUD-002**: Implement LLM router in n8n or OpenClaw
  - Route by task label/category → appropriate LLM backend
  - Fallback chain: local → DeepSeek → Claude (escalate on failure or low confidence)
- [ ] **BUD-003**: Token budget and alerting
  - Daily/weekly token budget per tier
  - Alert when approaching limits (80% threshold)
  - Hard stop at budget cap to prevent surprise costs
- [ ] **BUD-004**: Cost tracking dashboard
  - Grafana panel: tokens consumed per tier, per task type, per day
  - Monthly cost projection based on rolling average

#### H2: Task Catalog & Autonomy Classification

> Define what agents can do, and how much supervision each task type requires.

- [ ] **CAT-001**: Define task catalog with autonomy levels
  - **Level 3 (autonomous)**: log triaje, uptime alert response, scheduled reports, data scraping, RSS digest
  - **Level 2 (checkpoint)**: content drafts, PR reviews, dependency updates, config changes
  - **Level 1 (assist only)**: architecture proposals, security-related changes, infra modifications
- [ ] **CAT-002**: Implement autonomy enforcement in n8n
  - Level 3: agent completes → logs result → no human needed
  - Level 2: agent completes → pauses → Slack approval → continues
  - Level 1: agent proposes → human implements → agent not involved in execution
- [ ] **CAT-003**: Define guardrails per level
  - Level 3 guardrails: max execution time, no git push, no external API calls beyond whitelist, output size limits
  - Level 2 guardrails: same as L3 + diff size limit, mandatory PR (no direct push)
  - Blast radius control: agent containers have no access to prod, SOPS keys, or infra repos

#### H3: Always-On Agent Loops

> Agents that run continuously without being triggered by human tasks.

- [ ] **LOOP-001**: Monitoring response loop
  - Uptime Kuma alert → n8n → agent triages (checks logs, recent deploys, known issues)
  - If known pattern: auto-remediate (restart container, clear cache) + log
  - If unknown: escalate to Slack with diagnosis summary
- [ ] **LOOP-002**: Daily digest loop
  - Agent runs at 07:00: scrape RSS feeds, GitHub notifications, calendar, Vikunja backlog
  - Produce morning briefing → Slack DM or Telegram
  - LLM tier: DeepSeek (cheap, bulk text)
- [ ] **LOOP-003**: Content pipeline loop
  - Agent monitors content queue in Vikunja (label: `content:draft`)
  - Produces draft → pushes to blog repo branch → Slack notification for review
  - LLM tier: DeepSeek for first draft, Claude for polish (if budget allows)
- [ ] **LOOP-004**: Data analysis loop
  - Scheduled: weekly metrics summary from Prometheus/Grafana
  - Agent fetches data, generates trend analysis, flags anomalies
  - Output: Slack report or Vikunja task if action needed

#### H4: Scaling & Evaluation

> Measure agent effectiveness. Scale what works, kill what doesn't.

- [ ] **EVAL-001**: Agent effectiveness metrics
  - Tasks completed autonomously (L3) vs requiring intervention
  - Time saved per task type (estimate vs manual baseline)
  - Error rate: agent mistakes requiring human correction
  - Cost per task type
- [ ] **EVAL-002**: Weekly agent review (human ritual)
  - Review agent activity log
  - Promote tasks from L2 → L3 if consistently approved without changes
  - Demote tasks from L3 → L2 if error rate exceeds threshold
  - Retire agents/loops that don't deliver value
- [ ] **EVAL-003**: Scale decision framework
  - When to add more agent loops (value proven, budget available)
  - When to add hardware (RPi 4 saturated, need second agent host)
  - When to upgrade LLM tier for a task type (quality matters more than cost)

**Done when**: Agents operate 24/7 on defined task catalog, LLM routing minimizes cost,
autonomy levels enforced, effectiveness measured and reviewed weekly.

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
- [ ] GitHub secrets/vars cleanup: fix naive filter in `setup-gh-secrets`, separate `vars` (non-sensitive) from `secrets`, add `DOCKERHUB_USERNAME` to vars, document required CI credentials

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
| **core** | Essential platform | gitea, portainer, n8n, vaultwarden, vikunja |
| **observability** | Monitoring/logging | grafana, loki, uptime, prometheus, node-exporter, cadvisor |
| **security** | Auth/protection | authelia, crowdsec |
| **data** | Storage | minio |
| **automation** | CI/workflows | github-runner |
| **ai** | ML/AI agents | openclaw, picoclaw, pollex (llama.cpp) |
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

### 2026-02-14

- [x] A3 completed: full local integration (11 endpoints verified, all green)
- [x] `toolkit credentials show` command: decrypt and display SOPS secrets
- [x] `toolkit services down --all` / `up --all`: operate all components at once
- [x] Gitea stack created (compose.base + dev/staging/prod)
- [x] MinIO compose.dev.yml created (OIDC disabled for local dev)
- [x] Kestra removed (redundant — n8n chosen in ADR-007)
- [x] Docmost removed (redundant — Quartz chosen in ADR-008)
- [x] Wiki stack removed from infra/stacks/apps/ (will be `cubelab docs` in C1)
- [x] Fix: portainer domain in dev.yaml (YAML duplicate key overwrite)
- [x] Fix: SECRETS_DIR moved from AutheliaConfig to PATH_STRUCTURES
- [x] Makefile: replaced kestra with gitea in setup-local-dns
- [x] Vault: credentials model documented in sops-and-secrets.md runbook

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

*Last updated: 2026-02-15*
*Next action: A4 (push, PR, CI green), then B0 (hardware provisioning with new gateway architecture)*
*Streams: A (stabilize) → B (homelab) → C (repo split) → D (data/observability) → F (agents) → G (knowledge base) → H (agent workforce)*
