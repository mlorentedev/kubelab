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
**Template**: vault `10_projects/kubelab/06-products/product-template.md`

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
- Node: ace1 (172.16.1.2) — single all-in-one (no separate agents since ADR-023 Phase 1)
- Kubeconfig: `~/.kube/kubelab-{env}-config` (e.g. `kubelab-staging-config`)
- Deploy: `make deploy-k8s ENV=staging` (Kustomize only — Helm chart removed, ADR-021 Rev2)
- K8s packaging: custom apps (api/web/errors) = Kustomize, third-party = Helm official charts (H2 pending)

### VPN mesh

- Headscale v0.28.0 on VPS, Tailscale on 8 nodes (3 legacy VMs removed 2026-03-19)
- Split DNS zones defined in `networking.staging_zones` (common.yaml SSOT) → Headscale → RPi4 Pi-hole → CoreDNS → K3s
- Staging DNS is VPN-only. Prod DNS is Cloudflare (Terraform).

## Critical gotchas

- **Kustomize namespace override**: HelmChartConfig and cluster-scoped resources must NOT be in kustomization.yaml if it has `namespace:`. Apply separately.
- **VPS Docker network**: `kubelab` (migrated from `proxy` in ADR-020 Phase 2b, 2026-03-15)
- **VPS ACME storage**: `/letsencrypt/acme.json` (mount: `./certs/acme.json:/letsencrypt/acme.json`)
- **VPS Traefik managed by Ansible**: `traefik_vps` role templates all config from common.yaml. Deploy via `make deploy-vps`. Do NOT edit VPS files manually.
- **Traefik certResolver name is `letsencrypt`** (NOT `cloudflare` — cloudflare is the DNS challenge provider, not the resolver name)
- **Headscale v0.28 has no HTTP /health endpoint**: Use `docker inspect --format '{{.State.Health.Status}}'` for health checks, not `curl /health`
- **Pi-hole v6**: `pihole reloaddns` does NOT reload dnsmasq configs — use `docker restart pihole`
- **Headscale v0.28**: CLI uses numeric IDs (`--user 2`), routes via `nodes approve-routes`
- **Authelia on K8s**: MUST set `enableServiceLinks: false` — K8s injects `AUTHELIA_*` env vars that conflict with Authelia config. Also set `automountServiceAccountToken: false` (read-only `/run`).
- **Binary assets in K8s**: Use kustomize `configMapGenerator` with `files:` (NOT inline binaryData, NOT imperative kubectl). See `authelia-assets` and `grafana-dashboards` patterns.
- **Toolkit deploy vs kustomize**: `tk infra k8s deploy` may miss binary ConfigMaps from configMapGenerator. Fallback: `kubectl kustomize | kubectl apply -f -`
- **Authelia secrets key path**: `apps.services.security.authelia.*` (NOT `apps.authelia.*` or `apps.security.authelia.*`)
- **K8s base manifests have staging-hardcoded domains**: IngressRoutes and ConfigMaps in `infra/k8s/base/` use `*.staging.kubelab.live`. Prod overlay uses `patches.yaml` via Kustomize `patches:` to override. Do NOT add base-conflicting resources to the overlay's `resources:` list — use patches instead.
- **Kustomize `patchesStrategicMerge` is deprecated**: Use `patches: [{path: file.yaml}]` instead.
- **Headscale MUST stay outside K3s** (ADR-015): Bootstrapping dependency — K3s nodes need Tailscale, Tailscale needs Headscale. Headscale runs in Docker Compose on VPS permanently, even after K3s migration.
- **VPS K3s migration uses Pattern C** (ADR-015): Side-by-side with alternate ports (8080/8443), then swap to 80/443 at cutover. Never run two Traefik instances on the same ports.
- **K3s prod TLS SAN**: Must include both `162.55.57.175` (public) and `100.64.0.2` (Tailscale). Configure BEFORE first K3s start.
- **K8s ConfigMaps MUST NOT contain SOPS-sourced values**: The K8s generator merges values YAML + SOPS. `SECRET_PATTERNS` blocklist filters secrets from ConfigMaps, but it's fragile. Rule: if a value is in SOPS, it goes in a K8s Secret via `k8s_secrets.py`, NEVER in a ConfigMap. Review generated ConfigMaps before committing.
- **Never hardcode IPs/CIDRs in K8s manifests, tests, or toolkit code**: All network addresses live in `networking.*` in `infra/config/values/common.yaml`. K8s manifests that duplicate values MUST have a comment noting the common.yaml key they mirror. Tests MUST read from common.yaml via `yaml.safe_load`. See B10 (SSOT) tasks for remaining gaps.
- **DNS wildcard covers services NOT on K3s**: `*.staging.kubelab.live` resolves to K3s (100.64.0.4) via CoreDNS wildcard. Services only on Docker Compose (gitea, n8n, minio, uptime_kuma) have no IngressRoute → Traefik returns self-signed cert. Mark with `skip_in_envs=("staging",)` in expectations.py.
- **Headscale split DNS must target `staging.kubelab.live` only** (NOT `kubelab.live`): Broad split DNS routes ALL `*.kubelab.live` queries to RPi4 — if RPi4 is down, prod domains (which have public Cloudflare records) become unreachable from VPN clients. Narrowing to `staging.kubelab.live` lets prod domains resolve via public DNS (1.1.1.1) regardless of RPi4 state. VPN-only bare-metal services (ollama, jetson) use Headscale `extra_records` instead. Changed 2026-03-03.
- **K8s secrets.yaml uses placeholders only**: Both staging and prod `secrets.yaml` contain `REPLACE_WITH_SOPS_VALUE`. Real values injected at deploy time via `toolkit infra k8s apply-secrets`. Never commit real secret values.
- **Authelia OIDC JWKS key injection**: Use `issuer_private_key` (NOT `jwks[0].key`) in configuration.yml. `_FILE` env vars only work for flat config keys, not array-indexed. Set `AUTHELIA_IDENTITY_PROVIDERS_OIDC_ISSUER_PRIVATE_KEY_FILE`.
- **CoreDNS on RPi4**: Deploy via `make deploy-dns` (SCP + docker restart). RPi4 is NOT part of K3s — it's a standalone Docker Compose host. Never mix `hosts` and `template` plugins in same CoreDNS zone when IPs differ (template overrides hosts). Prod zone uses explicit entries only.
- **Secret operations go through toolkit**: `toolkit secrets *` is the single entry point. Never use raw `sops` or `openssl` in Makefile. SECRET_CATALOG in `toolkit/features/secrets_manager.py` is the authoritative registry.
- **Headscale (`vpn.kubelab.live`) MUST resolve to public IP**: CoreDNS and `/etc/hosts` entries for `vpn.kubelab.live` must use `162.55.57.175` (public), NEVER `100.64.0.2` (Tailscale). Bootstrap services can't depend on VPN being up.
- **RPi4 Tailscale flags**: `--login-server=https://vpn.kubelab.live --accept-dns=false --advertise-routes=172.16.1.0/24`. All three are required. `tailscale-watchdog.timer` auto-reconnects every 5 min.
- **LAN nodes MUST use `--accept-routes=false`**: Nodes physically on 172.16.1.0/24 (ace1, ace2) must NOT accept Tailscale subnet routes. RPi4 advertises 172.16.1.0/24 — if a LAN node accepts it, Tailscale installs that route in table 52 via `tailscale0`, hijacking reply routing and breaking all inbound LAN traffic. Fix: `tailscale set --accept-routes=false`. Only remote nodes (workstation, VPS) need `--accept-routes=true`.
- **External services through K3s Traefik**: Bare-metal services (Ollama) use Service + EndpointSlice in `infra/k8s/base/external/`. Label: `kubelab.live/location: external`. Uptime Kuma removed from K3s (2026-03-19) — lives on RPi3 standalone, proxied via VPS Traefik.
- **CrowdSec bouncer auto-registration**: `postStart` lifecycle hook on CrowdSec deployment ensures bouncer is registered after every pod start. No manual `cscli bouncers add` needed.
- **Staging DNS zones are SSOT-driven**: `networking.staging_zones` in common.yaml feeds Headscale split DNS, CoreDNS Corefile, and Pi-hole forwarding. Add a new staging domain in one place, deploy VPS + DNS.
- **Jetson Nano (Ubuntu 18.04)**: Cannot reuse Ubuntu 24.04 Ansible roles. Use `raw` module. NetworkManager (not netplan). Static IP via `nmcli`. Pollex deployment lives in pollex repo, not kubelab.
- **yamllint directives inside `|` blocks don't work**: `# yamllint disable` is string content inside literal block scalars, not a YAML comment. yamllint max line-length is 130 (accommodates argon2 hashes).
- **Trunk-based development**: `master` is the only permanent branch. Feature branches use `feature/`, `fix/`, `hotfix/`, `chore/` prefixes. All PRs squash-merge to master. No `develop` branch.
- **RC versioning**: Feature branches produce `{next-version}-rc.{N}` Docker tags. Master produces stable `{version}` tags. No more `0.0.0-dev.{sha}` builds.
- **Errors service lives in `edge/errors/`** (not `apps/`). It's an edge service, not a platform app. CI path filter reflects this.
- **K3s HelmChartConfig managed by Ansible**: Template at `infra/ansible/roles/k3s_server/templates/traefik-helmconfig.yaml.j2`. Includes ACME config. Do NOT create static HelmChartConfig in `infra/k8s/`.
- **All nodes use NOPASSWD sudo**: SSH hardened + NOPASSWD on all nodes (2026-03-20). No `-K` needed. For NEW nodes, bootstrap NOPASSWD manually first, then provision with `make provision NODE=x ENV=y ASK_PASS=1`.
- **Pattern C ports are in prod.yaml only**: common.yaml has 80/443 (default). prod.yaml overrides to 8080/8443 for side-by-side validation. Do NOT put alternate ports in common.yaml.
- **Authelia does NOT auto-reload configuration.yml**: ConfigMap changes require pod restart. Long-term: use configMapGenerator hash suffix for automatic rolling updates.
- **Gitea OIDC CLI vs web process**: `gitea admin auth add-oauth` writes to SQLite but the web process caches in memory. Always restart Gitea after CLI auth changes.
- **K3s pods can't resolve external domains by default**: Add `coredns-custom` ConfigMap in kube-system with forward zones. Applied via `make deploy-k8s` (separate kubectl step outside Kustomize overlay).
- **error-pages middleware must NOT intercept 400-404**: Only 408, 429, 500-503. Application 4xx responses (401 auth, 404 not found) must pass through to API clients.
- **n8n K8s MUST set `enableServiceLinks: false`**: K8s injects `N8N_PORT=tcp://...` which n8n can't parse, causing basic_auth fallback mode. Same pattern as Authelia.
- **Authelia ForwardAuth MUST whitelist `authRequestHeaders`**: Exclude `Authorization` header. Browser caches basic auth credentials → sends `Authorization: Basic` → Authelia can't parse empty password → 403 loop. Whitelist: Cookie, Accept, X-Forwarded-*.
- **Traefik HelmChartConfig API**: Use `additionalArguments: ["--api.dashboard=true", "--api.insecure=true"]`. The `api:` Helm values don't work in K3s bundled chart.
- **Traefik HelmChartConfig ports**: `port` (container) must equal `exposedPort` (service). HTTP→HTTPS redirect uses container port. Mismatch → redirect includes wrong port (e.g., `:8443`).
- **Ansible inventory env-aware for k3s_servers**: common.yaml has ace1 as k3s_server. prod.yaml MUST override `networking.vps.ansible_groups` to add `k3s_servers` and `networking.nodes.ace1.ansible_groups` to remove it. Regenerate with `toolkit infra ansible generate --env prod`.
- **configure_oidc.py uses update-oauth**: When Gitea auth source exists with linked users, `delete` fails. Script uses `update-oauth --id N` to update config without breaking user linkages.
- **Authelia OIDC issuer is request-dependent**: Accessing discovery via internal URL → issuer is internal URL. Gitea OIDC must use EXTERNAL URL for discovery (browser OIDC flows use external issuer in JWT).
- **SOPS secrets not auto-synced across envs**: When adding credentials to staging, manually add to prod too. Run `make secrets-audit` to detect gaps. TOOL-001/002 backlog items for automation.
- **PVC backup (ADR-024)**: CronJob in prod overlay. Uses `sqlite3 .backup` for consistent SQLite snapshots. `make backup-pvc ENV=prod` for manual trigger. minio-data excluded (circular — deferred to Phase 5 Velero).
- **Traefik ACME persistence is REQUIRED**: K3s Traefik uses `emptyDir` by default for `/data/acme.json`. Every pod restart loses certificates and requests new ones from Let's Encrypt. Rate limit: 5 certs per domain set per 168h. Add `persistence.enabled: true` to HelmChartConfig.
- **VPS `ansible_host` must use `public_ip`**: VPS hosts Headscale (bootstrap). Using Tailscale IP creates circular dependency — can't reach VPS to fix Tailscale when Tailscale is down. Generator uses `vps.get("public_ip")`. Kubeconfig must also use public IP (162.55.57.175:6443).
- **K3s `resolv-conf` on systemd-resolved hosts**: Must set `resolv-conf: "/run/systemd/resolve/resolv.conf"` in K3s config.yaml. Default `/etc/resolv.conf` contains `127.0.0.53` (stub) which isn't reachable from pods. Without this, CoreDNS can't forward external queries and ACME fails.
- **Docker containers need explicit `dns:` on systemd-resolved hosts**: Host `/etc/resolv.conf` has `127.0.0.53` which is the pod/container's own loopback, not the host's resolver. Add `dns: [1.1.1.1, 8.8.8.8]` to compose services. Parameterized as `docker_dns_servers` in Headscale role.
- **Headscale `override_local_dns` must be `false`**: `true` makes Tailscale override ALL clients' system DNS with MagicDNS (100.100.100.100). If VPN is down, ALL DNS fails. With `false`, only split DNS zones are affected.
- **`deploy-vps` skips Traefik/errors when K3s is active**: `when: "'k3s_servers' not in group_names"` on traefik_vps and errors roles. Prevents Docker Compose Traefik from stealing ports 80/443 from K3s Traefik in prod.
- **Headscale K8s routing (prod only)**: After K3s cutover, vpn.kubelab.live needs IngressRoute + Service + EndpointSlice in prod overlay (`headscale.yaml`). Headscale stays in Docker Compose (ADR-015) but K3s Traefik handles TLS termination. TLSOption `headscale-http11` forces HTTP/1.1 ALPN for Noise protocol.
- **Loki prod IngressRoute uses `.local` TLD**: Patched to `tls: {}` (no certResolver). ACME can't issue certs for non-public TLDs.

## Workflow rules

- **Commits**: User commits manually or via Claude when explicitly requested. Never commit autonomously.
- **Branching**: Trunk-based development. `master` only. PRs with squash merge. See CI workflows.
- **IaC-first**: Version-controlled config > declarative > automated > manual.
- **Source of truth**: `infra/config/values/*.yaml` (never .env files)
- **VPS is ARM**: Multi-arch Docker builds (amd64+arm64) required.
- **Never clone repos on deployment targets** — VPS/servers are not dev machines.

## Key paths (repo)

```
infra/k8s/                         — K8s manifests (base + overlays)
infra/config/values/               — Environment config (dev/staging/prod)
infra/stacks/                      — Docker Compose stacks (local dev)
infra/ansible/roles/k3s_server/    — K3s server provisioning (ADR-020 Phase 3)
infra/ansible/roles/k3s_agent/     — K3s agent provisioning
infra/ansible/roles/errors/        — Error pages container (VPS)
infra/helm/                        — Helm charts for third-party services (ADR-021 Rev2, H2 pending)
edge/                              — Traefik, DNS gateway configs
edge/errors/                       — Error pages source (Dockerfile + HTML)
toolkit/                           — Python CLI (will become kubelab-cli)
apps/                              — Application source (api, web, blog)
.github/workflows/                 — CI pipeline
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
01-adrs/                   — Architecture Decision Records
02-runbooks/               — Operational runbooks
03-troubleshooting/        — Troubleshooting guides
04-infra/                  — Infrastructure docs (DNS, networking)
05-hardware/               — Hardware allocation and topology
06-products/               — Product template
changelog.md               — Project changelog
```

### Task management conventions

- Every `[x]` MUST have a date: `✓ YYYY-MM-DD`
- Every `[!]` MUST reference blocker by task ID, not section name
- Completed tasks archived in `completed.md` (zero info loss)
- Product specs tracked in vault `10_projects/<product>/_index.md`
- Lessons that mature into critical gotchas → add to CLAUDE.md "Critical gotchas" section
