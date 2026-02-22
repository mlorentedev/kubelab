# KubeLab — Project Instructions

> Read entirely before any work. These instructions persist across machines via Git.

## What is KubeLab

Personal Internal Developer Platform (IDP). L0 infrastructure layer providing K3s, networking, observability, auth, and data services for a portfolio of products.

## Product Portfolio

KubeLab is one piece of a larger product ecosystem organized in 4 layers:

- **L0: kubelab** (this repo) — Infrastructure: K3s, Traefik, Headscale, DNS, Ansible, Terraform
- **L1: kubelab-*** — Platform services: cli, gateway, memory, agents, console
- **L2: apps** — imaging-suite, cubernautas (own repos, own identity)
- **L3: tools** — pollex, yt-intel, sec-scan (standalone, publishable without kubelab)

**Master index**: vault `10_projects/kubelab/portfolio.md`
**Product specs**: vault `10_projects/<product>/_index.md`
**Template**: vault `10_projects/kubelab/products/product-template.md`

### Product lifecycle

idea → spec → incubating (in this monorepo) → active (own repo) → stable

### This repo's scope

Only L0 infrastructure. Streams A, B, C3, D, E, G in vault `10_projects/kubelab/roadmap.md`.
Streams C1-C2, C4-C5, F, H, P have been extracted to product specs in the vault (2026-02-21).

## Architecture

### Hardware topology

```
VPS Hetzner (162.55.57.175)  — Production (Docker Compose → K3s in B6)
Acemagic-1 (12GB Proxmox)   — K3s server + agent-1 VMs (staging)
Acemagic-2 (12GB Proxmox)   — K3s agent-2 VM (heavy workloads)
Beelink (8GB)                — Ollama bare metal (LLM inference)
RPi 4 (8GB)                  — Network gateway: Pi-hole, CoreDNS, Headscale
RPi 3 (1GB)                  — External monitoring (Uptime Kuma)
Jetson Nano                  — Pollex (llama.cpp, independent project)
```

### K3s cluster

- v1.34.4+k3s1, namespace: `kubelab`
- Nodes: k3s-server (.10), agent-1 (.11), agent-2 (.12) on 172.16.1.0/24
- Kubeconfig: `~/.kube/kubelab-config`
- Deploy: `kubectl apply -k infra/k8s/overlays/staging/`

### VPN mesh

- Headscale v0.28.0 on VPS, Tailscale on 9 nodes
- Split DNS: `*.kubelab.live` → RPi4 Pi-hole → CoreDNS → cluster

## Critical gotchas

- **Kustomize namespace override**: HelmChartConfig and cluster-scoped resources must NOT be in kustomization.yaml if it has `namespace:`. Apply separately.
- **VPS Docker network**: `proxy` (NOT `kubelab`)
- **VPS ACME storage**: `/letsencrypt/acme.json`
- **DO NOT** overwrite VPS `traefik.yml` with toolkit-generated version
- **Pi-hole v6**: `pihole reloaddns` does NOT reload dnsmasq configs — use `docker restart pihole`
- **Headscale v0.28**: CLI uses numeric IDs (`--user 2`), routes via `nodes approve-routes`

## Workflow rules

- **Commits**: User commits manually. Provide commit message, never run `git commit`.
- **IaC-first**: Version-controlled config > declarative > automated > manual.
- **Source of truth**: `infra/config/values/*.yaml` (never .env files)
- **VPS is ARM**: Multi-arch Docker builds (amd64+arm64) required.
- **Never clone repos on deployment targets** — VPS/servers are not dev machines.

## Key paths (repo)

```
infra/k8s/                 — K8s manifests (base + overlays)
infra/config/values/       — Environment config (dev/staging/prod)
infra/stacks/              — Docker Compose stacks (local dev)
edge/                      — Traefik, DNS gateway configs
toolkit/                   — Python CLI (will become kubelab-cli)
apps/                      — Application source (api, web, blog)
.github/workflows/         — CI pipeline
```

## Vault location

All documentation, roadmaps, and operational knowledge lives in the Obsidian vault at `~/Projects/knowledge/`. This repo has NO `tasks/` or `docs/` directories — everything is in the vault.

### Vault paths for this project (`10_projects/kubelab/`)

```
roadmap.md                 — L0 infrastructure backlog (Kanban, active/pending tasks)
completed.md               — Archived completed tasks (full detail, zero info loss)
lessons.md                 — Patterns learned, gotchas, post-mortems
toolkit.md                 — Toolkit CLI documentation
testing.md                 — Testing strategy
versioning.md              — Versioning strategy
architecture-diagram.md    — Detailed architecture diagrams
portfolio.md               — Product portfolio master index
service-catalog.md         — Service catalog
runbooks/                  — Operational runbooks (19 guides)
adrs/                      — Architecture Decision Records (11 ADRs)
troubleshooting/           — Troubleshooting guides (17 categories)
```

### Task management conventions

- Every `[x]` MUST have a date: `✓ YYYY-MM-DD`
- Every `[!]` MUST reference blocker by task ID, not section name
- Completed tasks archived in `completed.md` (zero info loss)
- Product specs tracked in vault `10_projects/<product>/_index.md`
- Lessons that mature into critical gotchas → add to CLAUDE.md "Critical gotchas" section
