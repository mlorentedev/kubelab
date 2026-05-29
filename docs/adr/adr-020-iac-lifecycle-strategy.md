---
id: adr-020-iac-lifecycle-strategy
type: adr
status: active
created: "2026-03-15"
owner: manu
---

# ADR-020: Infrastructure as Code Lifecycle Strategy

## Status

Accepted (2026-03-15, revised same day). Supersedes ADR-004 scope. Extends ADR-012, ADR-014, ADR-015.

**Revision 2** (2026-03-15): Eliminated generated `group_vars` in favor of Ansible-native `include_vars` + `combine`. Roles redesigned as portable with self-contained defaults. Docker network standardized from `proxy` to `kubelab`. Phases 2+3 merged; all configs templatized from day one.

## Context

KubeLab infrastructure is managed through a mix of manual SSH commands, Makefile targets, toolkit CLI, Terraform, and stub Ansible roles. After the WEB-001k deploy session (2026-03-15), the gaps became clear:

- **3 new Makefile targets** created as stopgaps: `deploy-headscale`, `deploy-traefik-vps`, `k8s-apply`
- **VPS Docker Compose** (Headscale, Traefik) managed by hand, not provisioned as code
- **Node bootstrap** (SSH keys, Docker, Tailscale, K3s) is manual
- **Config generation** exists in toolkit but Ansible integration is incomplete (SSOT-005 blocked)
- **No single command** to reproduce the entire infrastructure from scratch

The goal: any machine can be reproduced from `git clone` + credentials. Everything generated from `common.yaml` (SSOT). Zero manual SSH.

### Current state (anti-pattern)

```
common.yaml → toolkit generates ... some things
Manual SSH → deploy configs to VPS, RPi4
Makefile targets → SCP + docker restart (not idempotent)
kubectl → manual apply with hardcoded image tags
Terraform → DNS only, no VPS provisioning
Ansible → 1 working role (dns_resilience), rest stubs
```

### Options evaluated

| Option | Description | Fit |
|--------|-------------|-----|
| A: Ansible-only | Ansible manages everything including K8s | Over-reach — kubectl/kustomize better for K8s |
| B: ArgoCD replaces Ansible for K8s | GitOps for apps, Ansible for nodes | Ideal long-term but adds Stream E dependency |
| C: Layered separation | Each tool owns one layer, toolkit orchestrates | Clear boundaries, incremental migration |

## Decision

### Layered IaC architecture (Option C)

Five layers, each with a single owner. Toolkit generates configs and orchestrates. No overlap between layers.

```
┌─────────────────────────────────────────────────────┐
│ Layer 0: Cloud Provisioning (Terraform)             │
│   Hetzner VPS · Cloudflare DNS · Storage Box        │
├─────────────────────────────────────────────────────┤
│ Layer 1: OS Bootstrap (Ansible)                     │
│   Base system · Docker · Tailscale · K3s · SSH keys │
├─────────────────────────────────────────────────────┤
│ Layer 2: Infrastructure Services (Ansible)          │
│   Headscale compose · Traefik compose + routes ·    │
│   CoreDNS compose · Pi-hole                         │
├─────────────────────────────────────────────────────┤
│ Layer 3: Platform Services (kubectl/Kustomize)      │
│   K8s manifests · overlays · secrets                │
├─────────────────────────────────────────────────────┤
│ Layer 4: App Deployment (CI/CD → kubectl)           │
│   Docker build · push · image tag update            │
└─────────────────────────────────────────────────────┘

Cross-cutting: common.yaml (SSOT) → toolkit generates ALL configs
```

### Tool boundaries

| Tool | Owns | Does NOT do |
|------|------|-------------|
| **Terraform** | Cloud resources (VPS, DNS, Storage Box) | Node config, app deploy |
| **Ansible** | Node provisioning, OS config, Docker Compose services outside K3s | K8s app deployment, DNS records |
| **kubectl/Kustomize** | K8s manifest apply, secrets injection | Node provisioning, cloud resources |
| **CI/CD (GitHub Actions)** | Build images, run tests, push to registry | Infrastructure provisioning |
| **Toolkit** | Config generation, orchestration (invokes all tools above) | Direct infrastructure changes |
| **Makefile** | Local dev shortcuts only (`make dev`, `make test`, `make lint`) | Remote deployments |

### Config generation flow (SSOT)

> **Updated in Revision 2**: Toolkit generates inventory ONLY. Ansible loads config natively.

```
common.yaml + {env}.yaml + common.enc.yaml (SOPS)
    │
    ├── toolkit infra ansible generate --env staging
    │   └── generates: inventory (hosts.yml) ONLY
    │
    ├── ansible-playbook (runtime)
    │   └── include_vars: common.yaml + {env}.yaml → combine → config dict
    │       └── playbook maps config → role variables → templates render
    │
    ├── toolkit infra terraform plan
    │   └── reads: dns.tfvars, services.json
    │
    ├── toolkit infra k8s deploy --env staging
    │   └── reads: values/*.yaml → kustomize overlays
    │
    └── toolkit config generate --env staging
        └── generates: env files, compose overrides
```

### Ansible roles (definitive list)

| Role | Layer | Target hosts | Replaces |
|------|-------|-------------|----------|
| `base_system` | 1 | all | Manual package install |
| `ssh_hardening` | 1 | all | Manual SSH config |
| `docker` | 1 | vps, rpi4, rpi3 | Manual Docker install |
| `tailscale` | 1 | all | Manual Tailscale registration |
| `k3s_server` | 1 | k3s-server | Manual K3s install |
| `k3s_agent` | 1 | k3s-agents | Manual K3s join |
| `dns_resilience` | 1 | all | Existing role (works) |
| `headscale` | 2 | vps | `make deploy-headscale` |
| `traefik_vps` | 2 | vps | `make deploy-traefik-vps` (full lifecycle: static config, dynamic routes, ACME, middlewares, network migration) |
| `nginx_errors` | 2 | vps | Manual nginx container (error pages for all Traefik routes) |
| `coredns` | 2 | rpi4 | `make deploy-dns` |
| `pihole` | 2 | rpi4 | Manual Pi-hole config |
| `health_check` | * | all | Manual curl verification |
| `backup` | * | vps, k3s-server | `toolkit infra backup` |

### Ansible inventory (generated from common.yaml)

```yaml
# Generated by toolkit — DO NOT EDIT
all:
  vars:
    ansible_user: deployer
    ansible_ssh_private_key_file: ~/.ssh/id_ed25519
  children:
    vps:
      hosts:
        kubelab-vps:
          ansible_host: "{{ networking.vps.tailscale_ip }}"
    k3s_servers:
      hosts:
        k3s-server:
          ansible_host: "{{ networking.nodes.k3s_server.tailscale_ip }}"
    k3s_agents:
      hosts:
        agent-1:
          ansible_host: "{{ networking.nodes.agent_1.tailscale_ip }}"
        agent-2:
          ansible_host: "{{ networking.nodes.agent_2.tailscale_ip }}"
    gateway:
      hosts:
        rpi4:
          ansible_host: "{{ networking.nodes.rpi4.tailscale_ip }}"
    monitoring:
      hosts:
        rpi3:
          ansible_host: "{{ networking.nodes.rpi3.tailscale_ip }}"
```

### Playbook structure

```
playbooks/
├── site.yml            # Full bootstrap (Layer 1 + 2)
├── provision.yml       # Layer 1 only (OS, Docker, Tailscale, K3s)
├── services.yml        # Layer 2 only (Headscale, Traefik, CoreDNS)
├── deploy-vps.yml      # VPS services (Headscale + Traefik)
├── deploy-dns.yml      # RPi4 CoreDNS
└── health-check.yml    # Post-deploy verification
```

### Makefile — final state after migration

Removed targets (replaced by Ansible via toolkit):
- `deploy-dns` → `toolkit infra ansible run --playbook deploy-dns`
- `deploy-headscale` → `toolkit infra ansible run --playbook deploy-vps`
- `deploy-traefik-vps` → `toolkit infra ansible run --playbook deploy-vps`
- `k8s-apply` → `toolkit infra k8s deploy --env staging`
- `k8s-cleanup` → removed (one-time operation)

Kept targets (local dev, no remote):
- `make setup` — local environment bootstrap
- `make dev` / `up-dev` / `down-dev` — Docker Compose local dev
- `make build-app APP=x` — local Astro/Go builds
- `make test` / `test-e2e` / `test-infra` — pytest suites
- `make lint` / `format` / `type` / `check` — code quality
- `make config-generate` — wrapper for toolkit config generate

### Secrets distribution flow

SOPS decrypts locally. Ansible pushes decrypted values to nodes.

```
common.enc.yaml (SOPS-encrypted)
    │
    toolkit decrypt → TF_VAR_* (Terraform)
    │                 ansible_vault_* (Ansible group_vars)
    │                 K8s Secrets (kubectl apply-secrets)
    │
    Ansible pushes to nodes:
    ├── VPS: Headscale config (no secrets in config.yaml)
    ├── VPS: Traefik TLS certs (Let's Encrypt via certResolver, auto-managed)
    ├── K3s: join token (generated by k3s-server, fetched by Ansible, pushed to agents)
    └── K8s: secrets.yaml populated by toolkit apply-secrets (existing pipeline)
```

Stateful data (Headscale SQLite, acme.json, PVCs) is NOT managed by Ansible.
Restore from backup is a prerequisite for "bootstrap from scratch" — see below.

### Bootstrap from scratch (disaster recovery)

Order matters. Dependencies are explicit.

```
1. Terraform apply (Layer 0)
   └── VPS exists, DNS ready, cloud-init creates deployer + SSH key

2. Ansible provision.yml --limit vps (Layer 1, PUBLIC IP — no VPN yet)
   └── Docker, Tailscale client (--login-server uses public IP per CLAUDE.md gotcha)

3. Ansible services.yml --limit vps (Layer 2)
   └── Headscale compose + Traefik compose
   └── Restore backup: Headscale SQLite + acme.json (from Hetzner Storage Box / local)

4. Headscale online → other nodes register via Tailscale
   └── Ansible provision.yml --limit homelab (Layer 1, uses Tailscale IPs now)
   └── Docker, K3s server, K3s agents

5. kubectl apply -k overlays/staging/ (Layer 3)
   └── toolkit infra k8s apply-secrets + kustomize

6. CI/CD pushes images (Layer 4)
```

**First-run vs day-2**: provision.yml roles are idempotent — skip-if-installed checks
built into each role. services.yml always copies latest config + restarts if changed.

### Bootstrap dependency DAG

```
Terraform (VPS exists)
    └── Ansible VPS bootstrap (Docker, Tailscale via PUBLIC IP)
        └── Headscale online (VPN control plane)
            ├── RPi4 registers → CoreDNS + Pi-hole deployed
            ├── K3s-server registers → K3s installed
            │   └── K3s-agents register → join cluster
            │       └── kubectl apply (apps running)
            ├── Beelink registers → Ollama running
            ├── RPi3 registers → Uptime Kuma running
            └── Jetson registers → Pollex running
```

Critical path: Terraform → VPS → Headscale → K3s-server → agents → apps.
RPi4/Beelink/RPi3/Jetson are parallel branches after Headscale.

### Node inventory — complete (including bare-metal)

All managed nodes, including those outside K3s:

| Node | Groups | Ansible user | Notes |
|------|--------|-------------|-------|
| kubelab-vps | vps, docker_hosts | deployer | Public IP for bootstrap, Tailscale after |
| k3s-server | k3s_servers, docker_hosts | manu | Proxmox VM |
| agent-1 | k3s_agents | manu | Proxmox VM |
| agent-2 | k3s_agents | manu | Proxmox VM |
| rpi4 | gateway, docker_hosts, dns_hosts | manu | CoreDNS, Pi-hole |
| rpi3 | monitoring, docker_hosts | manu | Uptime Kuma |
| beelink | compute, docker_hosts | manu | Ollama bare-metal |
| jetson | compute | manu | Python 3.6, raw module only |
| (future) cloud-node | personal_cloud, docker_hosts | manu | Stream CLOUD — Nextcloud + Immich |

Note: `ansible_user` differs per group (deployer for VPS, manu for homelab).

### SSOT generation scope

Everything generated from common.yaml. No manual config files.

| Generated artifact | Source | Generator |
|-------------------|--------|-----------|
| Ansible inventory | `networking.*` in common.yaml | `toolkit infra ansible generate` |
| ~~Ansible group_vars~~ | ~~`networking.*` + `apps.*`~~ | ~~Eliminated in Revision 2~~ — Ansible loads common.yaml natively via `include_vars` |
| dns.tfvars | `networking.vps.*` + zone IDs in common.yaml | `toolkit infra terraform generate` (new) |
| services.json | service catalog in common.yaml | `toolkit infra terraform generate` (new) |
| CoreDNS Corefile | `networking.*` + service domains | Ansible role template (was `toolkit infra dns generate`) |
| K8s overlays | `apps.*` in common.yaml | `toolkit infra k8s generate` (existing) |

### Implementation order (revised)

> **See Revision 2 for updated implementation order.** Original phases below kept for historical reference.

| Phase | Scope | Blocks | Why this order |
|-------|-------|--------|----------------|
| **Phase 1** | SSOT-005: dynamic inventory from common.yaml | Phases 2-4 | ✅ Done. Scope reduced: inventory ONLY |
| **Phase 2** | Layer 1 bootstrap + Layer 2 services with Jinja2 templates | Phase 3 | Merged original Phases 2+3. All configs templatized |
| **Phase 3** | K3s roles (server + agent) — unblocks B6 prod migration | B6 | Critical path |
| **Phase 4** | Terraform Hetzner VPS provisioning + backup/restore roles | Full reproducibility | Complete "from scratch" story |

## Revision 2: Architecture Refinements (2026-03-15)

### Problem with generated group_vars

During implementation planning, the generated `group_vars` approach (toolkit produces `group_vars/all.yml` from `common.yaml`) was identified as an anti-pattern:

- **Generator maintenance cost**: Every new variable requires Python code changes in `generator_ansible.py`
- **Indirection layer**: Data transformed unnecessarily (`common.yaml` → Python → `group_vars` YAML)
- **Drift risk**: If generator not re-executed after `common.yaml` changes, vars go stale at runtime
- **Role coupling**: Roles coupled to generated format, not portable to other projects

### New pattern: Ansible-native config loading

Ansible loads `common.yaml` + `{env}.yaml` directly at runtime via `include_vars` + `combine` filter. Zero generated group_vars. Zero custom Python for variable transformation.

```
common.yaml + {env}.yaml
    │
    ├── Ansible: include_vars + combine (runtime merge, zero drift)
    │   └── Playbook maps config paths → role variables (declarative YAML)
    │       └── Role templates render final configs on target
    │
    ├── Toolkit: generates ONLY inventory (hosts.yml)
    │   └── Irreplaceable — Ansible needs hosts before connecting
    │
    └── Toolkit: existing generators unchanged
        ├── Authelia config (templates → generated/)
        ├── K8s manifests (kustomize overlays)
        └── Docker Compose .env files (dev local)
```

### Playbook config loading pattern

Every playbook loads the SSOT at runtime using Ansible's native deep merge:

```yaml
pre_tasks:
  - name: Load base config (SSOT)
    include_vars:
      file: "{{ playbook_dir }}/../../config/values/common.yaml"
      name: common

  - name: Load environment overrides
    include_vars:
      file: "{{ playbook_dir }}/../../config/values/{{ deploy_env }}.yaml"
      name: env_overrides

  - name: Merge configs (env wins on conflict)
    set_fact:
      config: "{{ common | combine(env_overrides, recursive=True) }}"

roles:
  - role: headscale
    vars:
      headscale_image: "{{ config.apps.services.core.headscale.image }}"
      headscale_domain: "{{ config.apps.services.core.headscale.domain }}"
      headscale_listen_port: "{{ config.apps.services.core.headscale.default_port }}"
      vps_public_ip: "{{ config.networking.vps.public_ip }}"
      docker_network: "{{ config.network_name }}"
```

The mapping in the playbook IS the adapter layer — declarative YAML, not Python code. Visible, reviewable, greppable.

### Role design principles

1. **Portable**: Roles define their interface via `defaults/main.yml` with sensible fallbacks. They work without `common.yaml` — any project can provide the variables.
2. **Decoupled**: Roles reference their own variables (`headscale_image`), never `config.*` paths. The playbook does the mapping.
3. **Idempotent**: Every role handles both fresh install and config update. Tasks include create-if-missing + copy-if-changed + restart-if-needed.
4. **Self-contained**: Each role bundles templates, defaults, handlers, and tasks. No external template directories.
5. **Full lifecycle**: Service roles (Layer 2) handle the complete lifecycle: directory creation → compose + config templates → container pull → start → healthcheck. Not just config copy.

### SSOT hierarchy

```
common.yaml              ← Data: IPs, domains, images, ports (varies per env)
  ↓ include_vars + combine with {env}.yaml
Playbook vars mapping     ← Adapter: maps config paths → role variables
  ↓ role invocation
Role defaults/main.yml    ← Service config: remote paths, timeouts, options
  ↓ Jinja2 rendering
Role templates/*.j2       ← Structure: Corefile syntax, compose format
  ↓ copy to target
Final config on host      ← Output: rendered, never edit manually
```

The proof: changing one IP in `common.yaml` propagates to every config on every host with a single `ansible-playbook site.yml`. Zero files to touch beyond the source.

### Docker network standardization

**Deferred to Phase 2b.** Originally planned to rename `proxy` → `kubelab` during Phase 2, but discovered that all 11 VPS containers (Traefik, Headscale, API, web, Grafana, etc.) share the `proxy` network. Renaming requires atomic migration of all containers simultaneously — scope belongs in the `traefik_vps` role (Phase 2b), not in individual service roles.

`common.yaml` keeps `docker_network: proxy` for VPS until Phase 2b completes the atomic rename.

### Updated implementation order

Original Phases 2 (service roles) and 3 (bootstrap roles) merged into a single phase. Rationale: bootstrap roles are prerequisites for testing service roles against clean hosts, and templatizing during role creation has near-zero incremental cost vs retrofitting.

| Phase | Scope | Status | Changes from original |
|-------|-------|--------|-----------------------|
| **1** | SSOT-005: dynamic inventory from common.yaml | ✅ Done | Scope reduced: inventory ONLY, not group_vars |
| **2** | Layer 1 bootstrap (`base_system`, `ssh_hardening`, `tailscale`, refine `docker`) + Layer 2 services (`headscale`, `coredns`, `traefik_routes`) — all with Jinja2 templates | ✅ Done 2026-03-15 | Merged original Phases 2+3. All configs templatized |
| **2b** | Traefik VPS role (`traefik_vps`) — static config, ACME, docker network rename `proxy` → `kubelab` | ✅ Done 2026-03-15 | Atomic migration of 11 containers. Traefik v3.0→v3.6. Domains migrated *.mlorente.dev→*.kubelab.live. SOPS integration for secrets. |
| **3** | K3s roles (`k3s_server` + `k3s_agent`) | Blocked by Phase 2 | Was Phase 4. Unblocks B6 prod migration |
| **4** | Terraform VPS provisioning + backup/restore roles | Blocked by Phase 3 | Was Phase 5. Completes DR story |

### Scaling considerations

| Growth scenario | Impact | Mitigation |
|----------------|--------|------------|
| >15 roles with 10+ vars each | Playbook var mapping gets long | Extract to `playbooks/vars/{role}-mappings.yml` |
| >30 services in common.yaml | File exceeds 1000 lines | Split into `common.yaml` + `services.yaml` + `apps.yaml` |
| 50+ managed hosts | Inventory generation slower | Linear scaling, not a real concern |
| Multi-project reuse | Roles already portable | Only playbook mappings are project-specific |

None of these require architectural changes — only file reorganization.

## Consequences

**Positive**:
- Any node reproducible from `git clone` + credentials + `toolkit infra ansible run --playbook site.yml`
- Zero manual SSH for operations (except emergency debugging)
- Single source of truth (common.yaml) eliminates config drift
- Clear ownership boundaries — no tool overlap
- Each Makefile target created today becomes a regression test for the Ansible role that replaces it
- Portfolio demonstrates full IDP lifecycle design (L0 infra done right)

**Negative**:
- Ansible learning curve for roles not yet implemented (~2-3 weeks of work)
- Generator needs enhancement to produce dynamic inventory (SSOT-005)
- Temporary dual-path during migration (Makefile targets coexist with Ansible until fully replaced)

**Constraints**:
- Headscale MUST remain in Docker Compose on VPS (ADR-015 — bootstrapping dependency)
- VPS Traefik main config (`traefik.yml`) managed separately from dynamic routes (CLAUDE.md gotcha)
- Jetson Nano has Python 3.6 — roles must use `raw` module fallback (existing pattern in dns_resilience)
- VPS bootstrap uses PUBLIC IP (162.55.57.175), not Tailscale — VPN depends on Headscale being up first
- Stateful data (SQLite, acme.json, PVCs) requires backup restore, not Ansible provisioning
- `ansible_user` differs per group: `deployer` for VPS, `manu` for homelab nodes

## References

- ADR-004: Ansible for configuration management (original scope — this ADR extends it)
- ADR-012: Environment strategy (dev/staging/prod separation)
- ADR-014: Secrets management (SOPS + toolkit pipeline)
- ADR-015: VPS K3s migration (Headscale stays in Compose)
- B9 tasks: ANSIBLE-001 through ANSIBLE-011
- B10 tasks: SSOT-001 through SSOT-011
- Pattern: `pattern-fix-small-debt.md` (fix simple debt immediately)
