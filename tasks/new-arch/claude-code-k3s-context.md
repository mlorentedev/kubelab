# CLAUDE.md Addendum: K3s Migration Context

> Add this section to the existing CLAUDE.md or place as a separate file
> that Claude Code reads as project context.

## Homelab Architecture Change (2026-02-18)

The KubeLab homelab architecture is migrating from Docker Compose staging to Kubernetes (K3s) staging. This is a deliberate transition to build SRE skills and eventually migrate production to K3s as well.

### Hardware Allocation (UPDATED)

Previous plan had Acemagic as Docker Compose staging mirror and Beelink as Proxmox lab. This has been revised based on RAM constraints:

- **Acemagic (12GB)** → Proxmox VE 8.x → 3 VMs → K3s cluster (staging)
- **Beelink (8GB)** → Debian 12 bare metal → Ollama (AI inference)
- **Hetzner VPS** → Production (Docker Compose now, K3s single-node later)
- **RPi 4 (8GB)** → Network gateway: Pi-hole, CoreDNS, Tailscale (unchanged)
- **RPi 3 (1GB)** → External monitoring: Uptime Kuma (unchanged)
- **Jetson Nano** → Pollex AI: llama.cpp + Qwen 2.5 (unchanged)

### Deployment Flow

```
develop branch → ArgoCD → K3s cluster on Acemagic (staging)
master branch  → GitHub Actions → Hetzner VPS (production)
```

### Key Decisions

1. **Staging diverges temporarily from production**: Staging runs K3s, production runs Docker Compose. This violates the previous ADR "staging == prod" but is an intentional transition phase lasting max 3 months, after which production also migrates to K3s single-node.

2. **Ollama is external to K3s cluster**: Runs on Beelink bare metal, accessible via LAN at `http://<beelink-ip>:11434`. Apps in the cluster reference it as an ExternalName Service or environment variable. Do NOT create K3s manifests for Ollama itself.

3. **Proxmox enables multi-node simulation**: 3 VMs on Acemagic (1 server + 2 agents) allow SRE exercises (node failure, pod rescheduling, rolling updates) that a single bare metal install cannot provide.

4. **Docker Compose work is NOT wasted**: Compose files are the direct input for K8s manifest generation. The mapping is:
   - services → Deployments
   - ports → Services
   - volumes → PVCs
   - environment → ConfigMaps/Secrets
   - Traefik labels → Ingress resources

5. **No GPU VPS in production**: If apps need LLM in production, use external APIs (OpenAI, Anthropic). Self-hosted GPU is not cost-effective for personal project volumes.

6. **RPi devices stay outside the cluster**: Pi-hole, CoreDNS, Uptime Kuma are network/monitoring infrastructure, not application workloads. They do NOT get K8s manifests.

### What Changes in the Codebase

When implementing this migration:

- **Stream B in `tasks/todo.md`** needs updating: Acemagic gets Proxmox + K3s instead of Ubuntu Server + Docker
- **Ansible roles** need new playbooks for Proxmox VM provisioning and K3s installation
- **New directory**: `infra/k8s/` for Kubernetes manifests (Deployments, Services, Ingress, ConfigMaps)
- **ArgoCD config**: Application definitions pointing to `infra/k8s/` in the git repo
- **`infra/config/values/staging.yaml`** needs K3s-specific values (currently assumes Docker Compose)
- **`infra/ansible/templates/group_vars/staging.template.yml`** needs rewrite: `infrastructure_type: k3s` instead of `docker-compose`

### What Does NOT Change

- Production deployment via GitHub Actions + Docker Compose (until Phase 2)
- Docker images (same images, different orchestration)
- App code (zero changes to API, web, blog)
- Domain strategy (mlorente.dev + kubelab.live)
- SOPS secrets management
- Edge infrastructure (RPi 4, RPi 3, Jetson)
- `infra/stacks/` directory with compose files (preserved as reference and for production)

### Migration Phases

1. **Now**: Complete Stream A (stabilize current monorepo), install Proxmox on Acemagic
2. **Phase 1 (0-3 months)**: K3s cluster running, apps deployed, ArgoCD configured, Ollama accessible from cluster
3. **Phase 2 (3-6 months)**: Migrate production VPS from Docker Compose to K3s single-node
4. **Phase 3 (future)**: Scale production if needed (add VPS nodes to cluster)

### Ollama Production Strategy

For production LLM needs:
1. Evaluate external API cost vs self-hosted cost
2. External API (OpenAI/Anthropic/Groq) wins for low volume
3. Only consider GPU VPS if sustained high-volume inference justifies the ~50-150 EUR/month cost
4. Never expose homelab Ollama to production via tunnel (latency, reliability, security)
