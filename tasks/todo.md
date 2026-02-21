# KubeLab - Roadmap

> **Goal**: Stabilize, deploy to production, extract repos, build homelab staging.
>
> **Methodology**: Kanban + XP practices (no sprints, no time-boxes)
>
> **Strategy**: Fix code → Local dev → CI → Homelab staging → Production VPS → Extract repos

### Progress (updated 2026-02-21)

```
Overall:  ████████░░░░░░░░░░░░░░░░░░  31% (81/260)

Stream A: ████████████████████░░░░░░  81% (26/33)  — Stabilize & Deploy
Stream B: ████████████████░░░░░░░░░░  62% (54/87)  — Homelab K3s ← ACTIVE
Stream C: ░░░░░░░░░░░░░░░░░░░░░░░░░░   0% (0/30)  — Repo Separation + Imaging Suite
Stream D: ░░░░░░░░░░░░░░░░░░░░░░░░░░   0% (0/18)  — Data & Observability
Stream E: ░░░░░░░░░░░░░░░░░░░░░░░░░░   0% (0/6)   — ArgoCD GitOps
Stream F: ░░░░░░░░░░░░░░░░░░░░░░░░░░   0% (0/28)  — Agent Task Mgmt
Stream G: ░░░░░░░░░░░░░░░░░░░░░░░░░░   0% (0/7)   — Knowledge Base
Stream H: ░░░░░░░░░░░░░░░░░░░░░░░░░░   0% (0/14)  — Agent Workforce
Stream P: ░░░░░░░░░░░░░░░░░░░░░░░░░░   0% (0/10)  — Portfolio Tools
Stream Z: ░░░░░░░░░░░░░░░░░░░░░░░░░░   0% (0/27)  — Backlog (newsletter, blog, API, perf)

Velocity:    ~6.2 tasks/session (74 tasks in ~12 sessions, Feb 3-21)
Remaining:   179 tasks ÷ 6.2/session ≈ 29 sessions
Schedule:    ~4.5 sessions/week → ~6.5 weeks → early April 2026
Next:        B5 Phase 6 (staging deploy — waiting on CI web build, then kubectl apply)
Focus:       KubeLab infra first (B1-B6) → then SensorTool + blog + newsletters
```

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
kubelab-cli              → Generic Python CLI (Typer+Rich)
                           Published on GitHub Packages + PyPI
                           Reads kubelab.yaml per project
                           Command: kubelab

kubelab-platform         → Infrastructure monorepo:
                           - Platform services (Traefik, Authelia, Grafana, Gitea, n8n...)
                           - KubeLab apps (api, web, personal blog)
                           - IaC (Ansible, Terraform)
                           - Edge configs
                           Consumes: kubelab-cli

cubernautas-blog         → Cubernautas blog (separate identity)
                           Independent repo, deployed on KubeLab infra
                           Consumes: kubelab-cli

sensortool               → B2B SaaS (FastAPI/Go + Astro), portable
                           Own compose stacks, overrides for shared infra
                           Consumes: kubelab-cli

future-static-sites      → Each static site in its own repo
                           Same pattern: kubelab.yaml + kubelab-cli
```

### Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Pattern | SDK Distribution + IDP | Versioned toolkit, consumers pin versions |
| Repos | 4+ (toolkit, platform, blog, sensortool) | Each portfolio-ready, independent lifecycle |
| Config file | `kubelab.yaml` per project | Namespaced, declarative |
| Package | `kubelab-cli` → command `kubelab` | PyPI + GitHub Packages |
| Shared infra | Platform services shared, data logically isolated | One PostgreSQL, separate DBs per app |
| Portability | Compose overrides (dev=local, prod=shared) | Env vars abstract the difference |
| Blog split | cubernautas = own repo, personal blog in platform | Different identities, different lifecycles |
| Wiki | Not deployed as app — lives in toolkit as `kubelab docs` | Auto-generated from kubelab.yaml, served locally or published to `docs.kubelab.live` |
| VPN | Headscale (self-hosted) + Tailscale clients | WireGuard underneath, self-owned, industry-relevant |
| Users | `manu` on homelab, `deploy` on VPS | Avoids `kubelab@kubelab-*` redundancy; others can substitute their username |
| K8s deploy | `kubectl apply -k` initially, ArgoCD in Stream E | Learn raw tools before abstractions |
| Portfolio | Army of small focused repos (like steipete) | Each solves a real problem, publicly useful |

### Domain Strategy

| Environment | Personal site | Platform services |
|-------------|--------------|-------------------|
| Local dev | `mlorente.test` | `*.kubelab.test` |
| Staging | `web.staging.kubelab.live` | `*.staging.kubelab.live` |
| Production | `mlorente.dev` | `*.kubelab.live` |

Terraform DNS: two zones (`mlorente.dev` + `kubelab.live`)

### kubelab.yaml Schema (Reference)

```yaml
# Example for kubelab-platform
project:
  name: kubelab-platform
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

> **Updated 2026-02-19**: 2x Acemagic (both Proxmox VE 9.1.5) + Beelink (Ubuntu 24.04, Ollama pending) + VPS (Docker Compose → K3s in B6).
> See vault [[hardware/_index]].

```
┌─────────────────────┬───────────────────────────────────────────┐
│  VPS Hetzner        │ Production — Docker Compose (initial)     │
│  162.55.57.175      │ kubectl apply -k overlays/prod (post-B6)  │
│  user: deployer     │ Headscale control plane runs here         │
├─────────────────────┼───────────────────────────────────────────┤
│  Acemagic-1 (12GB)  │ Proxmox VE 9.x — K3s server + agent VM   │
│  kubelab-ace1       │ VM k3s-server (5GB) + VM k3s-agent-1 (5GB)│
│  user: manu         │ Proxmox snapshots for SRE exercises       │
├─────────────────────┼───────────────────────────────────────────┤
│  Acemagic-2 (12GB)  │ Proxmox VE 9.x — K3s agent-2 VM          │
│  kubelab-ace2       │ VM k3s-agent-2 (~10GB) — heavy workloads  │
│  user: manu         │ Observability, data services              │
├─────────────────────┼───────────────────────────────────────────┤
│  Beelink 8GB        │ Ollama — bare metal                       │
│  kubelab-bee        │ Ubuntu Server 24.04 + Ollama (OpenAI API) │
│  user: manu         │ For agents (Stream F) + generic LLM tasks │
│                     │ Endpoint: http://<beelink-ip>:11434       │
├─────────────────────┼───────────────────────────────────────────┤
│  RPi 4 (8GB)        │ Network gateway + AI agents               │
│  kubelab-rpi4       │ Bridge/NAT, Pi-hole, CoreDNS, Headscale   │
│  user: manu         │ OpenClaw + PicoClaw                       │
│                     │ Smart plug on full homelab power strip     │
├─────────────────────┼───────────────────────────────────────────┤
│  RPi 3 (1GB)        │ External monitor — physically separate    │
│  kubelab-rpi3       │ Uptime Kuma (probes VPS+homelab)          │
│  user: manu         │ Built-in WiFi (direct to router, 10.0.0.157) │
├─────────────────────┼───────────────────────────────────────────┤
│  Jetson Nano #1     │ Pollex — independent project              │
│  kubelab-jet1       │ llama.cpp + Qwen 2.5, GPU inference       │
│  user: manu         │ Text polish + embeddings                  │
├─────────────────────┼───────────────────────────────────────────┤
│  Jetson Nano #2     │ Spare (backup for #1)                     │
└─────────────────────┴───────────────────────────────────────────┘
```

**User convention**: `manu` on all homelab nodes (prompt: `manu@kubelab-ace1`),
`deployer` on VPS for CI/CD deploys (not `kubelab` — avoids redundant `kubelab@kubelab-vps`).

### Deployment Flow

```
local dev      → toolkit → Docker Compose (workstation)
develop branch → kubectl apply -k overlays/staging → K3s staging (Acemagic-1 VMs + Acemagic-2 VM)
master branch  → kubectl apply -k overlays/prod → Docker Compose on VPS (pre-B6)
                                                → K3s single-node on VPS (post-B6)

ArgoCD: deferred to Stream E — learn raw kubectl first, add GitOps automation later.
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
  - dev.yaml: `*.kubelab.test` + `mlorente.test`
  - staging.yaml: `*.staging.kubelab.live`
  - prod.yaml: `*.kubelab.live` + `mlorente.dev`
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
  make setup-local-dns       # /etc/hosts: *.kubelab.test + mlorente.test
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
  # 200: mlorente.test, api.kubelab.test/health, blog.kubelab.test, auth.kubelab.test
  #      minio.kubelab.test/minio/health/live, console.minio.kubelab.test
  # 302: traefik.kubelab.test, grafana.kubelab.test, portainer.kubelab.test,
  #      status.kubelab.test, gitea.kubelab.test (→ Authelia SSO, expected)
  ```

- [x] **INT-007**: Verify Traefik routing (each domain → correct container)

  ```bash
  # All routers green in Traefik dashboard
  # Fixed: portainer had kubelab.live instead of kubelab.test (duplicate YAML key bug in dev.yaml)
  ```

- [x] **INT-008**: Clean teardown

  ```bash
  toolkit services down --all   # New --all flag implemented
  # Only buildx_buildkit_multiarch0 remains (Docker Buildx builder, not KubeLab)
  ```

**Completed**: 2026-02-14. Full stack up, 11 endpoints verified via HTTPS,
Traefik routes correctly, clean teardown with `toolkit services down --all`.

#### A4: Push, PR and CI

> Blocked by: A3 completed (local verified end-to-end)

- [x] **CI-001**: Push branch and create PR

  ```bash
  git push origin feature/blog-restruct
  gh pr create --base develop
  ```

- [x] **CI-002**: Monitor CI, fix broken paths if needed
  - Fixed: step ID mismatch (`version_logic` → `docker_version`) — Docker builds never ran
  - Fixed: semver branch reference (`main` → `master`)
  - Fixed: `security-events: write` permission for Trivy SARIF upload
  - Fixed: codeql-action v3 → v4, SARIF upload non-blocking
  - Fixed: gitleaks artifact conflict on parallel jobs (`continue-on-error`)
  - Fixed: gitleaks false positives from removed wiki docs (`.gitleaks.toml`)
  - Fixed: DockerHub credentials (missing `DOCKERHUB_USERNAME`, expired token)
  - Fixed: undefined `inputs.changed_apps_json` in release workflow

- [x] **CI-003**: Verify Docker builds in CI
  - Docker image pushed: `mlorentedev/kubelab-api:0.0.0-dev.{sha}`
  - Registry rebranded: `mlorente-{app}` → `kubelab-{app}`
  - Versioning reset from 0.0.1 (clean start)

**Completed**: 2026-02-16. PR to develop created, CI green, Docker build validated.

#### A5: Production Validation

> Blocked by: A4 completed. B1 (Headscale) recommended but not hard-blocking.
> VPS runs Docker Compose initially. K3s migration happens later in B6.
> Note: A5 deploys Docker Compose on VPS — independent of K3s staging (B5).

- [x] **PROD-001**: Verify SSH access to VPS ✓ 2026-02-20

  ```bash
  ssh deployer@162.55.57.175 "hostname && docker ps"
  # Fixed: SSH key was corrupted in authorized_keys, re-added via Hetzner Web Console
  # Hostname changed: mlorente-01 → kubelab-vps
  ```

- [ ] **PROD-002**: Verify/fix Terraform DNS (two zones)

  ```bash
  ENVIRONMENT=prod toolkit infra terraform plan
  # Must manage: mlorente.dev + kubelab.live
  ```

- [ ] **PROD-003**: Deploy stack on VPS (Docker Compose)

  ```bash
  ssh deployer@162.55.57.175
  docker compose -f compose.base.yml -f compose.prod.yml up -d
  ```

- [ ] **PROD-004**: Verify Traefik routing + TLS (Let's Encrypt)

  ```bash
  curl -I https://mlorente.dev
  curl -I https://api.kubelab.live/health
  ```

- [ ] **PROD-004b**: Upgrade Traefik v3.0 → v3.6 on VPS
  - Docker provider broken: API v1.24 too old for Docker Engine 29.x (min v1.44)
  - File provider works fine (current routing unaffected)
  - Upgrade aligns VPS with `common.yaml` (`traefik:v3.6`)

- [ ] **PROD-005**: Verify each public app/service
  - `https://mlorente.dev` (personal website)
  - `https://blog.kubelab.live` (cubernautas blog)
  - `https://api.kubelab.live` (API)
  - `https://grafana.kubelab.live` (monitoring)
  - Wiki not deployed — lives in toolkit (`kubelab docs serve`)

- [ ] **PROD-006**: Basic monitoring (Uptime Kuma probes + Grafana/Loki on VPS)

**Done when**: Apps publicly accessible with valid TLS on both domains, Docker Compose managing VPS, monitoring active.

---

### Stream B: Homelab K3s + Production Migration

> **Prerequisite for A5 (prod validation)**. Starts after A4 (CI green).
>
> **Architecture (2026-02-18)**: K3s on homelab staging. VPS starts with Docker Compose,
> migrates to K3s in B6. Compose in `infra/stacks/` for local dev only. K8s manifests in `infra/k8s/`.
>
> **Topology (hybrid)**:
> - **Acemagic-1 (12GB)**: Proxmox VE 9.x → 2 VMs (k3s-server 5GB + k3s-agent-1 5GB)
> - **Acemagic-2 (12GB)**: Proxmox VE 9.x → 1 VM (k3s-agent-2 ~10GB for heavy workloads)
> - **Beelink (8GB)**: Bare metal → Ollama (external to cluster, LAN access)
> - **VPS Hetzner**: Docker Compose (initial) → K3s single-node (B6)
>
> RPi 4 = network gateway (outside cluster). RPi 3 = external monitor (outside cluster).
> Jetson = Pollex (independent project, outside cluster).
> VPN: **Headscale** (self-hosted control plane on VPS) + Tailscale clients = WireGuard underneath.
> Deploy method: `kubectl apply -k`. ArgoCD deferred to Stream E.
>
> **ADRs**: [[adr-010-headscale-over-tailscale-cloud]], [[adr-006-k3s-homelab-staging]]
> **Hardware**: See vault [[hardware/_index]] for full specs and topology.

#### B0: Hardware Provisioning (manual, runbook-guided)

> User executes manually, following vault runbooks.

**Acemagic-1 → Proxmox VE:**

- [x] **HW-001**: Install Proxmox VE 9.1.5 on Acemagic-1 (`kubelab-ace1`) ✓ 2026-02-19 → see vault [[runbooks/proxmox-setup]]
- [x] **HW-002**: Create VM `k3s-server` (5GB RAM, 2 vCPU, 40GB disk, Debian 13, `172.16.1.10`) ✓ 2026-02-19
- [x] **HW-003**: Create VM `k3s-agent-1` (5GB RAM, 2 vCPU, 40GB disk, Debian 13, `172.16.1.11`) ✓ 2026-02-19

**Acemagic-2 → Proxmox VE (same as Acemagic-1):**

- [x] **HW-004**: Install Proxmox VE 9.1.5 on Acemagic-2 (`kubelab-ace2`, user: `manu`) ✓ 2026-02-19 → see vault [[runbooks/proxmox-setup]]
- [x] **HW-004a**: Create VM `k3s-agent-2` (10GB RAM, 4 vCPU, 50GB disk, Debian 13, `172.16.1.12`) on Acemagic-2 ✓ 2026-02-19

**Beelink → Ollama:**

- [x] **HW-005**: Install Ubuntu Server 24.04 LTS on Beelink (`kubelab-bee`, user: `manu`) ✓ 2026-02-19
- [x] **HW-006**: Install Ollama + LAN config (`OLLAMA_HOST=0.0.0.0`) ✓ 2026-02-19
- [x] **HW-007**: Pull qwen2.5:7b (~4.7GB, ceiling for 8GB RAM) + LAN inference verified from RPi 4 ✓ 2026-02-19

**Network (completed previously):**

- [x] **HW-008**: RPi 4 Ubuntu Server installed (`kubelab-rpi4`)
- [x] **HW-009**: RPi 3 Raspberry Pi OS Lite installed (`kubelab-rpi3`, `10.0.0.157`, WiFi built-in)
- [x] **HW-010**: Jetson Nano #1 JetPack + Docker (`kubelab-jet1`) — online, hostname renamed ✓ 2026-02-19
- [x] **HW-011**: USB 3.0 Ethernet on RPi 4 (uplink, 1 Gbps confirmed)
  - ⚠️ **BUG**: USB ETH adapter `enx00e04c690e15` shows NO-CARRIER after reboot — RPi 4 WAN falls back to WiFi (`wlan0`). Investigate: cable? adapter? NetworkManager config?
- [x] **HW-012**: Ethernet RPi 4 → TP-Link switch (downlink)
- [x] **HW-013**: RPi 3 direct to home router (independent path)
- [x] **HW-014**: Beelink + Jetson + Acemagic-1 + Acemagic-2 on switch ✓
- [x] **HW-015**: dnsmasq DHCP on RPi 4 (172.16.1.0/24, MAC reservations)
- [x] **HW-016**: RPi 4 NAT gateway (nftables masquerade + IP forwarding)
- [x] **HW-017**: Copy SSH keys to all new devices (Acemagic-1, Acemagic-2, Beelink, Jetson) ✓ 2026-02-19
- [x] **HW-018**: Internet via RPi 4 bridge verified (Jetson: 0% loss)

> Runbook: vault [[runbooks/hardware-setup]]

#### B-pihole: Pi-hole on RPi 4 (parallel with B1)

> Pi-hole runs on RPi 4 (gateway node) alongside CoreDNS. All DNS consolidated.

- [x] **PIHOLE-001**: Deploy Pi-hole container on RPi 4 ✓ 2026-02-19
  - Disabled systemd-resolved (port 53 conflict), Docker volumes for persistence
- [x] **PIHOLE-002**: Configure Pi-hole — `listeningMode=ALL` for LAN access ✓ 2026-02-19
- [x] **PIHOLE-003**: dnsmasq `dhcp-option=6,172.16.1.1` — LAN devices get Pi-hole via DHCP ✓ 2026-02-19
  - Home router (Xfinity) blocks DNS config — workaround: per-device or via Headscale (B1)
- [x] **PIHOLE-004**: Verify DNS resolution + ad blocking from LAN (ace1 → google.com ✓, ads.google.com blocked ✓) 2026-02-19

> Runbook: vault [[runbooks/pihole-setup]]

#### B1: Headscale + Tailscale VPN Mesh

> **VPN decision**: Headscale (self-hosted control plane on VPS) + Tailscale clients.
> WireGuard protocol underneath. Self-owned coordination = industry-relevant skill.
> Cloudflare Tunnel stays only for Pollex public HTTP API (separate concern).

- [x] **TS-001**: Deploy Headscale on VPS (Docker Compose, port 8080 + DERP port 3478) ✓ 2026-02-21
  - Headscale v0.28.0 at `/opt/headscale/` on VPS
  - Traefik route: `app-headscale.yml` in `/opt/traefik/dynamic/`
  - TLS cert issued via Let's Encrypt DNS challenge (Cloudflare token needs both zones)
  - VPS Docker network is `proxy` (not `kubelab`)
  - ACME storage: `/letsencrypt/acme.json` (not `/etc/traefik/acme/`)
- [x] **TS-002**: Install Tailscale client on all nodes ✓ 2026-02-21
  - 9 nodes registered: msi, kubelab-vps, kubelab-bee, kubelab-jet1, kubelab-k3s-agent-1, kubelab-k3s-agent-2, kubelab-k3s-server, kubelab-rpi3, kubelab-rpi4
  - User: `kubelab` (ID 2). Pre-auth keys: `--user 2` (v0.28 uses numeric IDs)
- [x] **TS-003**: Configure kubelab-rpi4 as subnet router (`--advertise-routes=172.16.1.0/24`) ✓ 2026-02-21
  - `--accept-dns=false` required on RPi4 (Pi-hole node, no systemd-resolved)
  - `/etc/resolv.conf` → `127.0.0.1` + `chattr +i` (prevents Tailscale DNS chicken-and-egg)
- [x] **TS-004**: Approve subnet route in Headscale admin ✓ 2026-02-21
  - v0.28 CLI: `headscale nodes approve-routes -i 5 --routes 172.16.1.0/24`
  - Route verified: Approved + Serving
- [x] **TS-005**: Record Tailscale IPs for all devices, update SSH config ✓ 2026-02-21
  - IPs recorded in vault [[runbooks/headscale-setup]] Phase 4 and [[hardware/_index]]
  - SSH config: VPN primary (`ssh <host>`), LAN fallback (`ssh <host>-lan`)
  - Documented in vault runbook Phase 5 (reference for new workstation setup)
- [x] **TS-006**: Configure Tailscale split DNS for `*.staging.kubelab.live` → kubelab-rpi4 CoreDNS ✓ 2026-02-21
  - Headscale config: `split: { staging.kubelab.live: [100.64.0.5] }`
  - Chain: Headscale split DNS → Pi-hole (53) → CoreDNS (5353) → 100.64.0.4
  - Pi-hole v6: requires `etc_dnsmasq_d = true` in pihole.toml for conditional forwarding
  - Workstation: `--accept-routes` needed to use subnet router

> Runbook: vault [[runbooks/headscale-setup]]

#### B2: CoreDNS on RPi 4 (parallel with B3)

> CoreDNS runs alongside Pi-hole on RPi 4 gateway.
> Resolves `*.staging.kubelab.live` → K3s Ingress IP (Traefik on cluster).

- [x] **DNS-001**: Deploy CoreDNS container on RPi 4 (`edge/dns-gateway/`) ✓ 2026-02-21
  - Port 5353 (Pi-hole owns 53). Avahi disabled (`systemctl disable avahi-daemon avahi-daemon.socket`)
  - Pi-hole conditional forward: `server=/staging.kubelab.live/172.17.0.1#5353` in dnsmasq volume
  - Pi-hole v6: `etc_dnsmasq_d = true` in pihole.toml (FTL ignores dnsmasq.d by default)
- [x] **DNS-002**: Update Corefile: `*.staging.kubelab.live` → 100.64.0.4 (k3s-server Tailscale IP) ✓ 2026-02-21
  - Explicit hosts block + wildcard template catch-all
- [x] **DNS-003**: Verify: `dig api.staging.kubelab.live` → 100.64.0.4 ✓ 2026-02-21
  - Full chain verified: workstation → Headscale split DNS → Pi-hole → CoreDNS → 100.64.0.4

> Runbook: vault [[runbooks/dns-homelab]]

#### B3: K3s Cluster Setup

> Blocked by: B0 (hardware provisioned)

**K3s installation:**

- [x] **K3S-001**: Install K3s server on `k3s-server` VM (Acemagic-1) — v1.34.4+k3s1, done 2026-02-20

  ```bash
  curl -sfL https://get.k3s.io | sh -
  ```

- [x] **K3S-002**: Join `k3s-agent-1` VM (Acemagic-1) to cluster — done 2026-02-20

  ```bash
  curl -sfL https://get.k3s.io | K3S_URL=https://172.16.1.10:6443 K3S_TOKEN=<token> sh -
  ```

- [x] **K3S-003**: Join `k3s-agent-2` VM (Acemagic-2 Proxmox) to cluster — done 2026-02-20
- [x] **K3S-004**: Verify: `kubectl get nodes` → 3 nodes Ready — done 2026-02-20
- [x] **K3S-005**: Create namespace `kubelab` — done 2026-02-20
- [x] **K3S-006**: Configure `kubectl` access from workstation — done 2026-02-20

**Ollama as external service:**

- [x] **K3S-007**: Ollama as Service + EndpointSlice (172.16.1.3:11434) — done 2026-02-20

  ```bash
  kubectl get svc ollama -n kubelab        # ClusterIP → 11434
  kubectl get endpointslice -n kubelab     # ollama-external → 172.16.1.3
  # Pods use: http://ollama.kubelab.svc:11434
  ```

#### B4: K8s Manifests + kubectl deploy

> Blocked by: B3 (cluster running).
> No ArgoCD yet — learn raw kubectl first, add GitOps automation in Stream E.
> Deploy method: `kubectl apply -k overlays/staging/` (Kustomize built-in to kubectl).

**Directory structure:**

- [x] **MANIFEST-001**: Create `infra/k8s/` directory structure

  ```
  infra/k8s/
  ├── base/                  # Common manifests
  │   ├── namespace.yaml
  │   ├── apps/              # api, web, blog → Deployments + Services
  │   ├── services/          # authelia, grafana, loki, etc.
  │   └── edge/              # Ingress / IngressRoute resources
  └── overlays/
      ├── staging/           # Kustomize: 1 replica, staging domains, low limits
      │   └── kustomization.yaml
      └── prod/              # Kustomize: prod domains, real limits
          └── kustomization.yaml
  ```

**Convert Docker Compose → K8s manifests:**

- [x] **MANIFEST-002**: Convert app stacks (api, web, blog) → Deployments + Services
- [x] **MANIFEST-003**: Convert edge (Traefik labels) → Ingress resources or IngressRoutes
- [x] **MANIFEST-004**: Convert environment vars → ConfigMaps
- [x] **MANIFEST-005**: Convert secrets → K8s Secrets (conditional `secretRef` in deployment template + manual `kubectl create secret` for Cloudflare token. SOPS-encrypted git storage deferred to Stream E)
- [ ] **MANIFEST-006**: Convert volumes → PersistentVolumeClaims (where needed)
- [x] **MANIFEST-007**: Create Kustomize overlays for staging and prod
- [x] **MANIFEST-008**: Validate: `kubectl apply --dry-run=client -k overlays/staging/`
- [ ] **MANIFEST-009**: First deploy: `kubectl apply -k infra/k8s/overlays/staging/`

#### B5: Staging Deployment + Validation

> Blocked by: B1 (Headscale/Tailscale) + B2 (DNS) + B4 (manifests)

- [ ] **STAGE-001**: Apply staging overlay → all pods Running
  ```bash
  kubectl apply -k infra/k8s/overlays/staging/
  kubectl get pods -n kubelab
  ```
- [ ] **STAGE-002**: Verify Traefik Ingress routes (each domain → correct service)
- [ ] **STAGE-003**: Verify TLS (Let's Encrypt via DNS-01 or Traefik CRD)
- [ ] **STAGE-004**: Verify Ollama connectivity from cluster pods

  ```bash
  kubectl run test --rm -it --image=curlimages/curl -- \
    curl http://ollama.kubelab.svc:11434/api/tags
  ```

- [ ] **STAGE-005**: Deploy observability (Grafana, Loki) on K3s
- [ ] **STAGE-006**: Deploy security (Authelia + Redis, CrowdSec) on K3s
- [ ] **STAGE-007**: Smoke test ALL staging endpoints via Tailscale
- [ ] **STAGE-008**: Soak test: run staging ≥1 week, monitor stability

#### B6: Production K3s Migration (VPS)

> Blocked by: B5 validated (staging stable ≥1 week).
> Replaces Docker Compose on VPS with K3s single-node.
> Rollback plan: Docker Compose files in `infra/stacks/` remain as fallback.

- [ ] **PROD-K3S-001**: Install K3s single-node on Hetzner VPS

  ```bash
  curl -sfL https://get.k3s.io | sh -
  ```

- [ ] **PROD-K3S-002**: Apply prod overlay
  ```bash
  kubectl apply -k infra/k8s/overlays/prod/
  kubectl get pods -n kubelab
  ```
- [ ] **PROD-K3S-003**: Verify apps accessible with valid TLS on `mlorente.dev` + `kubelab.live`
- [ ] **PROD-K3S-004**: Update GitHub Actions: add `kubectl apply -k` deploy step on push to master
- [ ] **PROD-K3S-005**: Decommission Docker Compose on VPS (remove old containers, configs)
- [ ] **PROD-K3S-006**: Document rollback procedure: if K3s fails → `docker compose up` from `infra/stacks/`

**Done when**: staging == prod (both K3s), `kubectl apply -k` deploys to both.
Docker Compose only used for local dev. ArgoCD automation deferred to Stream E.

#### B-ai: Jetson Nano — Pollex (llama.cpp)

> Separate project ([[../../pollex/_index|Pollex]]), routed through staging Traefik via Ingress.
> Qwen 2.5 1.5B Q4_0, full GPU offload on Jetson Nano Maxwell GPU.

- [ ] **AI-001**: Install Docker on Jetson Nano (JetPack environment)
- [ ] **AI-002**: Deploy llama-server with Qwen 2.5 1.5B Q4_0 model (GPU offload `-ngl 999`)
- [ ] **AI-003**: Deploy Pollex Go API (browser extension backend, port 8090)
- [ ] **AI-004**: Add Traefik IngressRoute or ExternalName Service → Jetson LAN IP
- [ ] **AI-005**: Add CoreDNS entry for `polish.staging.kubelab.live`
- [ ] **AI-006**: Verify end-to-end: browser extension → Traefik → Pollex API → llama-server → response

#### B7: External Monitoring (RPi 3)

> Blocked by: B5. RPi 3 connects directly to router (independent internet),
> outside RPi 4 blast radius. Monitors both homelab and VPS.

- [x] **MON-001**: Install Docker on RPi 3 (`kubelab-rpi3`) ✓ 2026-02-18
- [ ] **MON-002**: Install Tailscale on RPi 3 (access internal services for probes) — blocked by B1
- [x] **MON-003**: Deploy Uptime Kuma v2 on RPi 3 — monitors: VPS, RPi 4, router ✓ 2026-02-18
- [ ] **MON-004**: Configure monitors for all staging K3s endpoints (via Tailscale)
- [ ] **MON-005**: Configure monitors for all prod endpoints (public URLs)
- [ ] **MON-006**: Configure alerts (Telegram/email)

#### B8: Documentation & Cleanup

- [x] **DOC-001**: Update `tasks/lessons.md` with session learnings
- [x] **DOC-002**: Rewrite Stream B in `tasks/todo.md`
- [x] **DOC-003**: Update vault hardware/_index.md (correct specs, topology, all devices)
- [x] **DOC-004**: Create vault runbooks (pihole-setup, proxmox-setup)
- [x] **DOC-005**: Update vault runbooks/hardware-setup.md (all devices)
- [x] **DOC-006**: Fix Ansible staging template
- [x] **DOC-007**: Add hardware verification lesson to tasks/lessons.md
- [ ] **DOC-008**: Create ADR for K3s migration strategy in vault
- [ ] **DOC-009**: Update vault hardware/_index.md with new allocation (2x Acemagic, Beelink → Ollama)
- [ ] **DOC-010**: Update vault runbooks as phases complete (tailscale, dns, deployment, k3s-setup)
- [ ] **DOC-011**: Update CLAUDE.md with final architecture
- [x] **DOC-012**: Create vault runbook `k3s-setup.md` (from B3 interactive session) — done 2026-02-20
- [ ] **ANSIBLE-001**: Fix docker_service role env var injection (only passes DOMAIN, needs all flattened vars from values.yaml)
- [ ] **ANSIBLE-002**: Add `toolkit config generate` env file output (`infra/config/env/{env}.env`) for Ansible deployment
- [ ] **ANSIBLE-003**: Fix Ansible inventory template (user: deployer, path: /opt/kubelab)
- [ ] **ANSIBLE-004**: Create Ansible role for K3s node provisioning (post-OS setup: SSH keys, packages, K3s install)
- [ ] **ANSIBLE-005**: Create Ansible role for homelab node provisioning (Docker, packages, network config)
- [ ] **ANSIBLE-006**: Create Ansible role for Headscale VPN provisioning
  - Deploy Headscale container on VPS (`/opt/headscale/`, `proxy` network, config from repo)
  - Add `app-headscale.yml` to `/opt/traefik/dynamic/` (without touching traefik.yml)
  - Create user, generate pre-auth key
  - Install Tailscale + register on all inventory nodes (`tailscale up --login-server=...`)
  - Configure subnet router on rpi4 (`--advertise-routes=172.16.1.0/24`)
  - Approve routes via `headscale routes enable`
  - Idempotent: skip already-registered nodes, skip existing Headscale user
  - Inputs: Cloudflare API token (SOPS), Headscale user name, node list from inventory
  - Ref: vault [[runbooks/headscale-setup]] for manual procedure
- [ ] **ANSIBLE-007**: Create Ansible role for Traefik dynamic route deployment
  - Copy individual `app-*.yml` files to `/opt/traefik/dynamic/` on VPS
  - Do NOT touch `traefik.yml` (managed separately until PROD-004b aligns VPS with toolkit)
  - Source files from `edge/traefik/generated/prod/dynamic/`

---

### Stream C: Repo Separation

> Prerequisite: A5 completed (prod working = safety net for repo split).
> This implements the architecture decisions above.
>
> **IMPORTANT — Pre-C4 checkpoint (Imaging Suite / SensorTool):**
> Before writing any SensorTool code, do audience building FIRST:
> 1. Setup Beehiiv for Imaging Sales Intel newsletter (30 min)
> 2. Write 4 newsletter issues batch (4h) — you already know the content
> 3. Publish 3 LinkedIn posts positioning as imaging sensor expert (1h)
> 4. THEN start coding SensorTool
> Reason: market validation is confirmed (insider), but audience = 0. Every week
> of audience before launch = warmer reception on day 1. ISO 24942 window is 2-3 years.

#### C1: Make toolkit generic

> This is the largest piece of work. Transform the toolkit from KubeLab-specific
> to generic, reading kubelab.yaml.

- [ ] **TOOLKIT-001**: Design definitive kubelab.yaml schema
  - Define what is configurable vs convention
  - Document with examples for: platform, app, static-site

- [ ] **TOOLKIT-002**: Implement kubelab.yaml loading
  - Parser with Pydantic v2 model
  - Sensible fallbacks if config is missing
  - Clear error if kubelab.yaml does not exist

- [ ] **TOOLKIT-003**: Refactor constants.py and settings.py
  - Remove hardcoded paths (PATH_STRUCTURES, SERVICES_*, etc.)
  - Everything resolves from kubelab.yaml + smart defaults

- [ ] **TOOLKIT-004**: Refactor cli/services.py
  - Discover stacks from kubelab.yaml, not from constants
  - Generic compose file resolution

- [ ] **TOOLKIT-005**: Refactor features/ (validation, generators)
  - Make generators configurable via kubelab.yaml
  - Validation reads structure from config

- [ ] **TOOLKIT-006**: Full tests for generic toolkit
  - Test with kubelab.yaml type platform
  - Test with kubelab.yaml type app
  - Test with kubelab.yaml type static-site
  - Edge cases: missing config, partial config

- [ ] **TOOLKIT-007**: Create kubelab.yaml for current monorepo
  - Verify toolkit works identically with config file

- [ ] **TOOLKIT-008**: Integrate wiki as `kubelab docs` (replaces wiki app)
  - Migrate `generator_wiki.py` to `kubelab docs` command
  - Subcommands: `generate` (static HTML), `serve` (local MkDocs), `validate` (CI)
  - Reads project structure from `kubelab.yaml`:
    - Auto-generated service catalog (apps, services, domains, versions)
    - Available commands (CLI introspection)
    - Project architecture
  - Remove wiki app from stack (Dockerfile, compose, Traefik domain)
  - Local access: `kubelab docs serve` → `http://localhost:8000`
  - Tests:
    - `kubelab docs validate` passes without errors
    - `kubelab docs generate` produces valid HTML
    - `kubelab docs serve` starts server on configurable port
    - Content reflects kubelab.yaml (correct service catalog)
  - Publication (post C2, when kubelab-cli is an independent repo):
    - CI in `kubelab-cli` generates static HTML with `kubelab docs generate`
    - Automatic deploy to GitHub Pages (`mlorente.github.io/kubelab-cli/`)
    - On VPS: Nginx/Traefik serves static HTML at `docs.kubelab.live`
    - Traefik route points to a lightweight container (nginx:alpine) with generated HTML
    - Option: GitHub Action in kubelab-cli deploys to VPS via SSH/rsync
    - Result: `docs.kubelab.live` always up-to-date with each CLI release

**Done when**: Toolkit works the same as before but reading kubelab.yaml.
Zero KubeLab-specific hardcoded logic. `kubelab docs serve` serves
auto-generated project documentation.

#### C2: Publish kubelab-cli

> Blocked by: C1 completed

- [ ] **PUB-001**: Create `kubelab-cli` repo on GitHub
  - Structure: pyproject.toml, kubelab_cli/, tests/, README
  - Move toolkit/ code to new repo

- [ ] **PUB-002**: Configure toolkit CI/CD
  - Tests on PR
  - Publish to GitHub Packages on tag
  - Publish to PyPI on tag

- [ ] **PUB-003**: First release (v0.1.0)

  ```bash
  cd kubelab-cli
  poetry version 0.1.0
  poetry publish --build
  ```

- [ ] **PUB-004**: Verify clean installation

  ```bash
  pip install kubelab-cli
  kubelab --help
  ```

**Done when**: `pip install kubelab-cli` works, `kubelab --help` responds.

#### C3: Convert monorepo → kubelab-platform

> Blocked by: C2 completed (toolkit published)

- [ ] **PLAT-001**: Update pyproject.toml
  - Remove toolkit as local code
  - Add dependency: `kubelab-cli = "^0.1.0"`

- [ ] **PLAT-002**: Clean toolkit/ directory from monorepo
  - Only kubelab.yaml remains as configuration

- [ ] **PLAT-003**: Verify everything works with external toolkit

  ```bash
  poetry install
  kubelab services list
  kubelab services up web
  ```

- [ ] **PLAT-004**: Clean repo rename references (`mlorente.dev` → `kubelab`)
  - GitHub URLs in README.md, CONTRIBUTING.md, common.yaml
  - Go module path in `apps/api/src/go.mod` + all `.go` imports
  - pyproject.toml metadata
  - Makefile/pre-commit comments
  - `toolkit/features/orchestrator.py` hardcoded health check URLs
  - Note: `mlorente.dev` as DOMAIN stays (it's the personal site domain, not the repo name)

- [ ] **PLAT-005**: Update CI/CD to use kubelab-cli as dependency

**Done when**: Monorepo works without local toolkit, consumes kubelab-cli from PyPI.

#### C4: Imaging Suite (SensorTool + SensorDB)

> **Blocked by**: C2 completed (toolkit published). Can be done in parallel with C3.
>
> **Context**: Imaging Suite is a B2B SaaS platform for industrial image sensor comparison
> (SensorDB) and EMVA 1288 / ISO 24942 analysis (SensorLab) via WebAssembly.
> See `~/Downloads/imaging-suite-business-plan-v3.1.md` for full business plan.
>
> **Strategy**: Start inside KubeLab monorepo (apps/sensortool/), then extract to
> private monorepo (imaging-suite-platform) when stable. KubeLab provides infra
> (K3s, monitoring, auth, CI/CD), SensorTool is the product.
>
> **Tech stack**: Go API (SensorDB backend) + Astro frontend + Go→WASM (SensorLab browser engine)
> Core algorithms in Go compile to: binary (CLI), WASM (browser), Docker (CI/CD).

- [ ] **SENSOR-001**: Create `apps/sensortool/` inside KubeLab monorepo
  - Go API: `apps/sensortool/api/` (SensorDB endpoints: search, compare, export)
  - Astro frontend: `apps/sensortool/web/` (SensorDB UI + SensorLab WASM host)
  - WASM engine: `apps/sensortool/wasm/` (Go→WASM: EMVA 1288 algorithms)
  - Compose: `infra/stacks/apps/sensortool/`

- [ ] **SENSOR-002**: SensorDB schema and seed data
  - PostgreSQL schema: sensors table (specs normalizadas cross-vendor)
  - Seed with first 50 industrial sensors from public datasheets
  - Go API endpoints: `GET /sensors`, `GET /sensors/:id`, `GET /sensors/compare`

- [ ] **SENSOR-003**: SensorDB API — search, filter, compare
  - Filtros: resolución, framerate, rango espectral, interfaz, fabricante
  - Comparador lado a lado (hasta 5 sensores)
  - Selection Wizard (requisitos → ranking automático)
  - Export PDF/CSV/JSON

- [ ] **SENSOR-004**: SensorLab WASM engine (EMVA 1288 core)
  - Go core library: MTF, SNR, QE, Dynamic Range, Noise Floor
  - Compile to WASM with `GOOS=js GOARCH=wasm`
  - Zero-upload: imagen RAW procesada 100% en browser
  - Report generation (client-side PDF)

- [ ] **SENSOR-005**: Report Polish (LLM integration)
  - Pollex (Jetson) or Ollama (Beelink) for technical language optimization
  - API endpoint: `POST /reports/polish` → LLM-enhanced technical writing

- [ ] **SENSOR-006**: Auth and tiers (Free vs Pro $99/mes)
  - Authelia SSO or custom JWT
  - Stripe integration for Pro tier
  - Feature gating: free = 50 sensors + 5 searches/month, Pro = full access

- [ ] **SENSOR-007**: CI/CD within KubeLab pipeline
  - Go lint + build + WASM compile in CI
  - Docker build multi-arch
  - Deploy to staging K3s

- [ ] **SENSOR-008**: Extract to private monorepo `imaging-suite-platform`
  - Move from KubeLab apps/ to own repo when product is stable
  - Own CI/CD, own Stripe keys, own domain (sensortool.io)
  - KubeLab remains as infra provider (K3s, monitoring)

**Done when**: SensorDB searchable with 50+ sensors, SensorLab WASM runs in browser,
Free/Pro tiers work, deployed on KubeLab staging K3s.

#### C5: Extract cubernautas-blog

> Blocked by: C2 completed
> Can be done in parallel with C3 and C4.

- [ ] **BLOG-001**: Create `cubernautas-blog` repo on GitHub

- [ ] **BLOG-002**: Move blog content from kubelab-platform to new repo
  - Current blog (`apps/blog/`) → `cubernautas-blog/`
  - Current stack (`infra/stacks/apps/blog/`) → adapt to new repo

- [ ] **BLOG-003**: Create personal blog in kubelab-platform
  - Replace the blog that left with a personal one

- [ ] **BLOG-004**: kubelab.yaml + own CI/CD

- [ ] **BLOG-005**: Verify deploy on KubeLab infra

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

- [ ] **MET-008**: Create custom KubeLab overview dashboard
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
  - Domain: `tasks.kubelab.test` / `tasks.staging.kubelab.live` / `tasks.kubelab.live`
  - Resource limits, OIDC config (Authelia), SMTP for notifications

- [ ] **VIK-003**: Add Traefik route for Vikunja
  - Update templates or add to generated config
  - Authelia middleware for SSO login

- [ ] **VIK-004**: Deploy and verify Vikunja locally
  ```bash
  toolkit services up vikunja
  curl -I https://tasks.kubelab.test
  ```

- [ ] **VIK-005**: Configure initial project structure in Vikunja
  - Projects: `kubelab/infra`, `kubelab/apps`, `trabajo`, `personal`
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
> Agents run on RPi 4 (`kubelab-rpi4`, 8GB) — no GPU needed, uses external LLM APIs.

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
  - Task targeting repo outside kubelab (e.g., sensortool)
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
  - Domain: `kb.kubelab.test` / `kb.staging.kubelab.live` / `kb.kubelab.live`
  - Git repo URL for vault
  - Quartz config: published folders/tags whitelist

- [ ] **KB-003**: Configure Quartz content filtering
  - Define folder whitelist (e.g., `10_projects/kubelab/`, `20_areas/engineering/`)
  - Exclude sensitive folders (credentials, personal, private notes)
  - Tag-based filter: only notes tagged `public` or in approved folders
  - Verify: build output contains ZERO sensitive notes

- [ ] **KB-004**: Add Traefik route with Authelia middleware
  - `kb.kubelab.test` → knowledge-base container
  - Authelia SSO required (no anonymous access)

- [ ] **KB-005**: Deploy and verify locally
  ```bash
  toolkit services up knowledge-base
  # Should redirect to Authelia login first
  curl -I https://kb.kubelab.test
  # After auth: vault content visible, graph view works, wikilinks resolve
  ```

- [ ] **KB-006**: Verify sync cycle
  - Edit a note in Obsidian → push to Git
  - Wait 5 min (or trigger manual rebuild)
  - Verify: change appears on `kb.kubelab.test`

- [ ] **KB-007**: Verify security layers
  - Layer 1: unauthenticated request → Authelia redirect (no content leaked)
  - Layer 2: inspect built HTML → no sensitive folders/notes present
  - Verify excluded content is not in search index either

**Done when**: Vault accessible at `kb.kubelab.test` behind Authelia, auto-syncs from Git,
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

### Stream E: ArgoCD GitOps

> **Prerequisite**: Stream B completed (B6 — K3s running on both staging and prod).
> Add GitOps automation on top of working kubectl deploys.
> Deferred from B4 intentionally — learn raw kubectl before abstracting.

- [ ] **ARGO-001**: Install ArgoCD on staging K3s cluster (Acemagic-1)
- [ ] **ARGO-002**: Create ArgoCD Application for staging (source: `develop`, path: `infra/k8s/overlays/staging`)
- [ ] **ARGO-003**: Install ArgoCD on prod K3s (VPS) and configure for `master` branch
- [ ] **ARGO-004**: Enable auto-sync for staging, manual-sync for prod (safer)
- [ ] **ARGO-005**: Replace manual `kubectl apply` in CI with ArgoCD sync trigger
- [ ] **ARGO-006**: Configure ArgoCD notifications → Slack on sync success/failure

---

### Stream P: Portfolio Tools

> **Goal**: Extract and publish standalone tools from KubeLab. Pattern: small focused repos,
> each solving a real personal problem but useful to others. Like steipete's army of repos.
> Prerequisite: C1 completed (toolkit decoupled — kubelab-cli is the reuse pattern to follow).

#### P1: Pollex MCP Server

> Pollex already exists as a complete Go project (llama.cpp API on Jetson).
> Add MCP server adapter so Claude Code and other MCP clients can use it directly.
> Low effort: thin wrapper over existing HTTP API.

- [ ] **POL-001**: Design MCP server interface for Pollex
  - Endpoint: `polish(text)` → polished text via local Qwen 2.5
  - MCP tool definition in Go
- [ ] **POL-002**: Implement MCP server in Pollex Go codebase
  - Add `cmd/mcp-server/main.go` alongside existing `cmd/server/`
  - Reuse existing adapter pattern (llama.cpp/Ollama/Claude/Mock)
- [ ] **POL-003**: Test with Claude Code MCP integration
  - Register in `~/.claude.json` as local MCP server
  - Verify: Claude Code can call Pollex for text polish tasks
- [ ] **POL-004**: Update Pollex README with MCP usage section
- [ ] **POL-005**: Tag release on GitHub (pollex is already public, MIT)

#### P2: yt-intel CLI

> YouTube intelligence CLI extracted from `apps/workers/youtube/`.
> Currently buried in monorepo as a Celery worker. Extract as standalone Python CLI.
> Portfolio value: solves a real problem (YouTube channel analysis) with clean CLI UX.

- [ ] **YT-001**: Create `yt-intel` repo on GitHub
  - MIT license, pyproject.toml (uv or Poetry), Typer + Rich CLI
- [ ] **YT-002**: Extract `apps/workers/youtube/` → `yt-intel/`
  - Remove Celery dependency (sync CLI, no queue needed for standalone use)
  - Keep: transcript download, channel analytics, metrics, export
- [ ] **YT-003**: CLI design
  ```
  yt-intel analyze <channel-id>     # Full channel report
  yt-intel transcript <video-id>    # Get transcript
  yt-intel export <channel-id> --format json|csv|md
  ```
- [ ] **YT-004**: README with demo GIF, install instructions, examples
- [ ] **YT-005**: CI: tests + publish to PyPI on tag
  ```bash
  pip install yt-intel
  yt-intel analyze @mkbhd
  ```

---

### Stream Z: Backlog (unprioritized)

> Items without defined order. Prioritize when capacity or need arises.

**Tier 1: Likely**

- [ ] Workers deployment: compose files in `infra/stacks/apps/workers/`
- [ ] Workers Phase 2: Media processing (FFmpeg, WebP)
- [ ] Test coverage: 30%+ on toolkit core modules
- [ ] DNS cleanup + Terraform automation: Audit and clean all DNS records on both `kubelab.live` (Cloudflare) and `mlorente.dev` (Cloudflare). Remove stale/unused records, keep only what's active. Then automate via Terraform Cloudflare provider — generate records from `common.yaml` service catalog so DNS stays in sync with deployed services
- [ ] Terraform DNS: Generate `services.json` from `common.yaml`
- [ ] SOPS alignment: Align with age keys from dotfiles
- [ ] GitHub secrets/vars cleanup: fix naive filter in `setup-gh-secrets`, separate `vars` (non-sensitive) from `secrets`, add `DOCKERHUB_USERNAME` to vars, document required CI credentials
- [ ] Docker image cleanup: purge stale `0.0.0-dev.*` tags from DockerHub (retention policy or GitHub Action cleanup job)
- [ ] Dependency vulnerability audit: `go get -u` (API), `npm audit fix` (web), `poetry update` (toolkit). Silence gosec TLS false positives with `//nolint:gosec`. Routine maintenance, not blocking
- [ ] CI build speed: single-arch for staging (amd64 only), eliminate double web build (npm ci runs in both ci-pipeline validation and Dockerfile), consider native ARM runners for prod multi-arch
- [ ] GitHub Issues as portfolio: create one Issue per stream as living epic (not per task). Retroactive summaries for completed streams (B0-B4), ongoing for active streams. Claude creates, user closes via PRs. Format: objective + checklist + key decisions + runbook links. ~10 issues total
- [ ] Git remote rename: update origin URL from `mlorente.dev.git` → `cubelab.git` (GitHub redirect works but cosmetic fix)
- [ ] API expansion (3 phases): Phase 1 = full portfolio API (projects, blog feed, CV, /status aggregator). Phase 2 = SensorDB backend. Phase 3 = microservices gateway. See brainstorm 2026-02-19
- [ ] Service performance tuning: resource limits, benchmarks, Ollama inference speed, K3s pod resource requests/limits
- [ ] Shared storage exploration: evaluate Longhorn (K3s native) vs NFS (Beelink) vs MicroCeph for Stream D. Needed when running stateful workloads (DBs, Minio) on K3s
- [ ] Blog content plan (Cubernautas): content batching strategy — accumulate vault notes during B1-B6, convert to 10-15 posts, publish 1/week with buffer. ES first, EN translation via agents (Stream H). First topics: homelab K3s, Pi-hole Docker, Headscale self-hosted, Ollama homelab, Proxmox VMs
- [ ] Newsletter — Imaging Sales Intel: Beehiiv (frontend) + PostgreSQL sync (backup). n8n cron exports subs via Beehiiv API weekly to own DB. Listmonk as documented plan B if Beehiiv fails. See imaging-suite-business-plan-v3.1.md
- [ ] Newsletter — Cubernautas: platform TBD (Beehiiv or shared Listmonk). ES audience, Platform Engineering content
- [ ] Newsletter subscriber persistence: n8n workflow to sync Beehiiv subscribers → PostgreSQL (both Imaging Sales Intel + Cubernautas). Single source of truth for all subscriber data. Export on schedule + webhook on new sub

**Tier 2: Possible**

- [ ] ClawdBot: Telegram bot (framework, approval workflow)
- [ ] Authelia expand: OIDC for more services
- [ ] Workers Phase 3: AI (embeddings, RAG, summarization)
- [ ] API as platform gateway: unified auth (Authelia JWT), rate limiting, service mesh entry point for all KubeLab services
- [ ] Blog analytics: self-hosted Plausible or Umami (privacy-first, no Google Analytics)
- [ ] Listmonk self-hosted (plan B): deploy on K3s if Beehiiv becomes unsuitable. Migration path: PostgreSQL backup → Listmonk import → DNS cutover
- [ ] CMOSBench SEO landing: public page with free MTF calculator + partial sensor DB. SEO targets: "CMOS sensor comparison", "EMVA 1288 calculator"

**Tier 3: Ideas (no commitment)**

- [ ] K3s multi-arch cluster with RPi #2
- [ ] Helm charts for all apps
- [ ] Workers Phase 4-5 (data aggregator, system maintenance)

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
kubelab services up <name>       # Start app or service
kubelab services down <name>     # Stop
kubelab services logs <name>     # View logs
kubelab services list            # List available
kubelab config generate          # Generate configs from templates
kubelab config validate          # Validate configs
kubelab credentials generate     # Generate credentials
kubelab infra ansible deploy     # Deploy with Ansible
kubelab infra terraform plan     # Terraform plan
kubelab deployment deploy        # Full deployment pipeline
kubelab dashboard                # Terminal dashboard
kubelab tools certs generate     # Generate local certs
kubelab docs serve               # Serve project documentation locally
kubelab docs generate            # Generate static HTML docs
```

---

## Completed

### 2026-02-17

- [x] PR merge to develop: feature/blog-restruct → develop
- [x] Fix: Astro 5 content collections (`resource.slug` → `resource.id`, `resource.render()` → `render(resource)`)
- [x] Fix: Docker web build — 3 chained issues (vite.define without JSON.stringify, NODE_ENV=production before build, unnecessary Rollup manual install)
- [x] Fix: CI gitops commit (`github.ref` → `github.head_ref` for PR events)
- [x] Fix: CI compose file path check (`apps/` → `infra/stacks/apps/`)
- [x] Updated browserslist (4.26→4.28) to fix baseline-browser-mapping warning
- [x] Vault: documented GitOps rebase gotcha in `runbooks/cicd.md`
- [x] CLAUDE.md: updated CI workflow reference (`ci-02-pipeline` → `ci-pipeline`)

### 2026-02-16

- [x] A4 completed: PR to develop, CI green, Docker build validated
- [x] CI pipeline: fix critical step ID mismatch, semver branch, permissions
- [x] Docker registry rebranded: `mlorente-{app}` → `kubelab-{app}`, versioning reset
- [x] DockerHub credentials: added `DOCKERHUB_USERNAME`, rotated expired token
- [x] Gitleaks: `.gitleaks.toml` to exclude removed wiki, `continue-on-error` for parallel jobs
- [x] Trivy: codeql-action v4, SARIF upload non-blocking
- [x] Vault: rewritten `runbooks/cicd.md` (4-workflow architecture, troubleshooting, secrets rotation)
- [x] Vault: updated `runbooks/secrets-and-variables.md` (dotfiles + SOPS dual system, rotation workflow)

### 2026-02-14

- [x] A3 completed: full local integration (11 endpoints verified, all green)
- [x] `toolkit credentials show` command: decrypt and display SOPS secrets
- [x] `toolkit services down --all` / `up --all`: operate all components at once
- [x] Gitea stack created (compose.base + dev/staging/prod)
- [x] MinIO compose.dev.yml created (OIDC disabled for local dev)
- [x] Kestra removed (redundant — n8n chosen in ADR-007)
- [x] Docmost removed (redundant — Quartz chosen in ADR-008)
- [x] Wiki stack removed from infra/stacks/apps/ (will be `kubelab docs` in C1)
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
- [x] Vault runbooks/proxmox-setup.md created: Proxmox VE 9.x on Acemagics, WiFi backup mgmt, bridge networking
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
- [x] Domain strategy defined: mlorente.dev (personal) + kubelab.live (platform)
- [x] Wiki decision: removed as deployed app, will integrate as `kubelab docs` in toolkit (C1/TOOLKIT-008)
- [x] Roadmap restructured: A1→A5 (added domain migration + local integration phases)
- [x] A2 completed: domain migration across all values/*.yaml files
- [x] Full .env elimination: deleted physical files, cleaned toolkit code, Ansible roles, CI workflows
- [x] Documentation updated: AGENTS.md rewrite, CLAUDE.md, 7 docs/README files migrated to values/*.yaml references
- [x] Ansible roles modernized: compose overlay pattern (compose.base.yml + compose.{env}.yml)

### 2026-02-08

- [x] Architecture decisions: SDK Distribution + IDP pattern
- [x] Define repos: kubelab-cli, kubelab-platform, sensortool, cubernautas-blog
- [x] Methodology change: Kanban + XP (no sprints)
- [x] Define kubelab.yaml schema
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

*Last updated: 2026-02-21*
*Next action: B5 (staging deploy — kubectl apply). B1+B2 complete. PROD-004b (Traefik upgrade) when convenient.*
*Streams: A (stabilize) → B (homelab K3s + prod migration) → C (repo split) → D (observability) → E (ArgoCD) → F (agents) → G (knowledge base) → H (agent workforce) → P (portfolio tools)*
