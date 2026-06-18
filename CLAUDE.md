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
**Template**: vault `00_meta/templates/product-template.md`

### Product lifecycle

idea → spec → incubating (in this monorepo) → active (own repo) → stable

### This repo's scope

Only L0 infrastructure. Streams A, B, C3, D, E, G in vault `10_projects/kubelab/roadmap.md`.
Streams C1-C2, C4-C5, F, H, P have been extracted to product specs in the vault (2026-02-21).

## Architecture

### Hardware topology (ADR-028: always-on vs on-demand)

```
ALWAYS-ON (24/7):
  VPS Hetzner (162.55.57.175) — Prod K3s: apps + observability + Gitea + PostgreSQL
  AWS t4g.small (2GB)          — ArgoCD hub (management plane)
  RPi 3 (1GB)                 — Uptime Kuma (external prod monitoring)

ON-DEMAND (homelab, powered when working):
  Acemagic-1 (12GB)           — K3s staging all-in-one (ace1)
  Beelink (8GB)               — CI + Storage + AI orchestration (GH Runner, MinIO, OpenClaw)
  Acemagic-2 (12GB)           — Ollama bare metal (LLM compute, ace2)
  RPi 4 (8GB)                 — Staging DNS gateway (CoreDNS, Pi-hole)
  Jetson Nano                 — Pollex (llama.cpp, independent project)
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
- **CrowdSec bouncer is a Traefik plugin (not ForwardAuth)**: Uses `maxlerebourg/crowdsec-bouncer-traefik-plugin` v1.5.1 (registered in HelmChartConfig `experimental.plugins`). No separate bouncer pod. API key read from file via `crowdsecLapiKeyFile` — Secret `crowdsec-bouncer-traefik` in `kube-system` mounted as volume in Traefik pod. Stream mode polls LAPI every 60s. `ClientTrustedIPs` whitelists Tailscale CIDR. Docker Compose dev still uses fbonalair ForwardAuth.
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
- **Argo CD OIDC is native (no dex)**: Uses `configs.cm.oidc.config` in Helm values. Client secret stored as `$oidc.authelia.clientSecret` in `configs.secret.extra`, injected by `deploy-argocd` via `--set`. Dex disabled (not needed with native OIDC). Admin local account is apiKey-only (CLI fallback). RBAC: Authelia `admins` group → `role:admin`.
- **deploy-argocd enforces OIDC order**: Makefile target runs `_deploy-authelia-oidc` (apply prod manifests + restart Authelia) before `_deploy-argocd-helm`. Authelia must have the OIDC client registered before Argo CD tries discovery.
- **Hub credentials always in common SOPS**: `argocd.admin_password`, `argocd.admin_password_hash`, and `oidc_client_secret_argocd` live in `common.enc.yaml`, not per-env. `credentials-generate` writes hub secrets separately via `batch_update_secrets(secret_file_path=common_sops)`.
- **Custom app default_port differs dev vs K8s**: common.yaml `default_port` is for dev (e.g., web=4321 Astro dev server). Staging/prod override to 8080 (nginx Docker). Always check port overrides when adding a new custom app to K8s.
- **Generated IngressRoutes include error-pages middleware**: All routes get `error-pages` by default in `_build_middlewares()`. Shows custom error page on 502/503/504 instead of raw Traefik "no available server".
- **K3s pods can't resolve external domains by default**: Add `coredns-custom` ConfigMap in kube-system with forward zones. Applied via `make deploy-k8s` through the `cluster_bootstrap` layer (ADR-047/TOOL-009): the toolkit renders its `RESOLVE_RPI4_TAILSCALE_IP` placeholder via MagicDNS and server-side applies it outside the Kustomize overlay. `optional: true` → skipped when RPi4 is off. (Was a hand-rolled `dig|sed|kubectl` in the removed `deploy-external` target until 2026-06-17.)
- **error-pages middleware intercepts 502/503/504 ONLY**: Industry standard — infrastructure errors where backend is unreachable. Application errors (4xx, 500, 429) must pass through to preserve JSON responses and rate-limit headers.
- **Custom app images need manual pin in kustomization.yaml**: `sync_k8s_images.py` only handles third-party images. After releasing a custom app (errors, api, web), update its tag in `infra/k8s/base/kustomization.yaml` `images:` section. `kubectl apply -k` may need `rollout restart` if image digest didn't change. Argo CD Image Updater (Phase 3) will automate this.
- **release-please ignores `chore:` for version bumps**: Only `fix:` (patch) and `feat:` (minor) trigger releases. If changes need a Docker image rebuild, use the appropriate prefix.
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
- **Argo CD scoped RBAC requires wildcard reads**: Argo CD cache discovers ALL K8s API resource types and does cluster-wide LIST. Enumerating resources explicitly breaks on K8s upgrades (new types like `ResourceClaim`). Standard pattern: `apiGroups: ["*"], resources: ["*"], verbs: ["get","list","watch"]` via ClusterRoleBinding for reads, scoped RoleBinding in `kubelab` for writes.
- **Argo CD `resource.exclusions` selector field**: May not filter by label as expected. To remove default EndpointSlice exclusion, set `resource.exclusions: ""` in argocd-cm ConfigMap. Manual EndpointSlices (external services) are safe with prune — Argo CD only prunes resources with its tracking label.
- **Hub t4g.small sizing**: 2GB RAM fits Argo CD with all components (7 pods, ~940MB). Upgraded from t4g.micro (2026-03-28) — 1GB caused OOM on every Helm upgrade. Full scale-down pre-upgrade still recommended as safety net. `make deploy-argocd` handles this automatically.
- **Hub↔spoke uses Tailscale, not public IP**: The CLAUDE.md rule "VPS must use public_ip" applies to bootstrap tools (Ansible, kubeconfig). Runtime services (Argo CD) use Tailscale IPs. Spoke API servers defined in `argocd.spokes` in common.yaml.
- **Pi-hole staging-only (VPN)**: `pihole.staging.kubelab.live` — RPi4 bare metal via LAN EndpointSlice. NOT in prod (RPi4 unreachable if VPN down, no public DNS). Pi-hole v6 has built-in auth — no Authelia middleware (causes redirect loop). Password in SOPS: `apps.services.network.pihole.admin_password`.
- **Middleware secret injection (ADR-035 Stage 1, AI-001)**: Traefik Middlewares that embed a plaintext SOPS-sourced API key (currently `api-key-ollama`, prod-only) are NOT in Kustomize/git. Toolkit `apply_middleware_secrets()` reads SOPS → renders `infra/k8s/overlays/<env>/middlewares/*.yaml.tpl` → writes gitignored audit copy to `infra/k8s/overlays/<env>/middlewares/.rendered/` → `kubectl apply -f -` via stdin (plaintext never on persistent disk). Triggered by `make apply-middleware-secrets ENV=x` (also auto-runs as part of `make deploy-k8s`). Adding a new auth-protected service requires three SSOT touches: `SECRET_CATALOG` (`secrets_manager.py`), `MIDDLEWARE_CATALOG` (`k8s_middlewares.py`), and a `.tpl` file. Plugin `dtomlinson91/traefik-api-key-middleware` v0.1.2 registered as `api-key:` in `traefik-helmconfig.yaml.j2` (alongside the CrowdSec `bouncer:` plugin). Plugin returns HTTP 403 (not 401) for any rejected request — see plugin README + ADR-035.
- **Shared infra services namespace (ADR-036)**: Values consumed by MORE THAN ONE component live at `infra.<service>.<attr>` in `common.yaml` (non-secrets) and SOPS (secrets). The toolkit ConfigMap generator (`generator_k8s.py:_extract_app_env_vars`) emits `INFRA_*` flattened keys into every component's ConfigMap AS-IS (no prefix stripping), so consumers in source code/Compose/Jinja reference the canonical name directly (e.g., `os.Getenv("INFRA_SMTP_USER")` in Go, `${INFRA_SMTP_USER}` in compose, `{{ INFRA_SMTP_USER }}` in Authelia template). First and currently only user: SMTP (`infra.smtp.{user,from,host,port,secure}` in common.yaml + `infra.smtp.pass` in SOPS). New shared services (Redis, queue, etc.) follow the same pattern without further generator changes. See ADR-036 in vault for full rationale.
- **Argo CD selfHeal per environment (ADR-037)**: `infra/k8s/argocd/applications/staging.yaml` runs with `syncPolicy.automated.selfHeal: false` — staging is a mutable test bed where `make deploy-k8s ENV=staging` from a feature-branch worktree must PERSIST long enough to run e2e against it. `applications/prod.yaml` keeps `selfHeal: true` — prod must self-correct drift immediately. Validation flow for any PR touching K8s state: (1) `make deploy-k8s ENV=staging` from worktree, (2) `make apply-secrets ENV=staging`, (3) `kubectl rollout restart deploy/<name> -n kubelab` against staging spoke, (4) `make test-e2e ENV=staging`. Only after green: merge to master, Argo CD prod auto-syncs.
- **Identity SSOTs (SSOT-014 master plan, 2026-05-25)**: three identity values were consolidated to single declarations in `common.yaml`:
  - **SSH user per node category (SSOT-014a)**: `networking.ssh_users.{homelab,cloud}` is the SSOT. Generators infer category by YAML position (vps + aws → cloud; nodes.* → homelab). Per-node `ssh_user` override remains supported but currently unused. Consumers: `generator_ansible.py`, `toolkit/cli/{infra,monitoring}.py`, `tests/infra/fixtures.py`, `check-vps-reachable.yml` (Jinja default with `, true` for empty/null fallback).
  - **Authelia admin user (SSOT-014b)**: admin entry uses `is_admin: true` flag; both `generator_authelia.py` and `k8s_secrets._build_users_database` resolve username from `apps.auth.admin_username` SSOT. SOPS password hash key follows resolved username (`users_<resolved>_password_hash`). Non-admin users keep explicit `username:` field.
  - **Operator contact email (SSOT-014c, closes SSOT-010)**: `apps.contact.email` SSOT in `common.yaml`. Loader (`configuration.py:_inject_contact_email_derivations`) fills empty/absent: `edge.traefik.acme_email`, `apps.services.observability.uptime_kuma.admin_email`, Authelia admin user email. **NOT applied to `infra.smtp.user`** — that is the SMTP relay account, semantically distinct (may legitimately differ from operator contact, e.g. `noreply@`). Per-field override remains supported.
  - **Distinction OS-user vs App-user**: `networking.ssh_users.homelab` is the OS-level Linux user that SSHes into the node (e.g. `manu`). `apps.auth.admin_username` is the Authelia/Gitea/Argo-CD identity (e.g. `operator` post-Phase-B). They coincided by historical accident — they are different concepts. Renaming the App-level is a 1-line edit; renaming the OS-level requires per-node migration (tracked as `SSH-RENAME-001`).
- **K8s manifests with hardcoded identity (SSOT-014 residual)**: `infra/k8s/base/services/authelia.yaml` notifier block (lines ~157-158) + `infra/k8s/overlays/prod/{patches,secrets}.yaml` contain literal email/username. These files are NOT in the generator output set — manual edits required when renaming. Documented as SSOT-010 partial residual. Adding them to the generator is a separate refactor.

## Workflow rules

- **Commits**: User commits manually or via Claude when explicitly requested. Never commit autonomously.
- **Branching**: Trunk-based development. `master` only. PRs with squash merge. See CI workflows.
- **New git worktree**: run `make worktree-init` once in every new worktree under `.worktrees/`. Installs the per-worktree `.venv` via Poetry (~30s first run, ~1s no-op afterwards). Pre-commit hooks are shared automatically via `core.hooksPath` set at `make setup` time — no per-worktree re-install needed.
- **IaC-first**: Version-controlled config > declarative > automated > manual.
- **Source of truth**: `infra/config/values/*.yaml` (never .env files)
- **VPS is ARM**: Multi-arch Docker builds (amd64+arm64) required.
- **Never clone repos on deployment targets** — VPS/servers are not dev machines.
- **Service placement principle (ADR-028)**: "Would I need this at 3 AM?" → always-on (VPS/AWS/RPi3). Otherwise → on-demand (homelab). Observability on prod, not staging. Embedding pipeline on VPS (autonomous). CI on Beelink with GitHub-hosted fallback.
- **Beelink is on-demand Platform Node (ADR-028)**: GH Runner + MinIO + OpenClaw + Glances. NOT Gitea, NOT Grafana (those go on VPS prod 24/7). Services here tolerate being offline when homelab is off.
- **CI runs on self-hosted runner (ADR-030)**: All workflows use `fromJSON(vars.RUNNER_DOCKER)` for runner routing. Toggle: `gh variable set RUNNER_DOCKER --body '["self-hosted","linux","docker"]'`. Fork PRs forced to `ubuntu-latest` (Docker socket = host access). Runner resources: 4CPU/6GB. Tool cache persists via `runner_toolcache` volume.
- **Docker buildx state corruption**: If `docker buildx inspect/create/rm` all fail for the same builder, clean filesystem state: `rm -rf /root/.docker/buildx/instances/<name>`. Caused by mixing `become: true/false` in Ansible Docker tasks.
- **ace2 is on-demand LLM compute (ADR-028)**: Ollama only. Previous services (MinIO, GH Runner) migrated to Beelink. Swap order: ANSIBLE-013 (Beelink gets services) THEN IDP-024 (ace2 loses them).
- **Ollama EndpointSlice IP changes with swap**: Currently `172.16.1.3` (Beelink) → will become `172.16.1.5` (ace2) after IDP-024. Update `infra/k8s/base/external/ollama.yaml`.

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

## Documentation & knowledge location

Project-bound knowledge lives in this repo under `docs/` (docs-as-code). Cross-project strategic context and session memory live in the maintainer's knowledge store, not here.

### Repo `docs/` (build/operate — versioned with the code)

```
docs/adr/                     — Architecture Decision Records
docs/architecture/            — system/design docs (overview, diagram, service-catalog, versioning)
docs/architecture/components/ — component-level architecture docs
docs/architecture/infra/      — infrastructure docs (DNS, networking)
docs/architecture/hardware/   — hardware allocation and topology
docs/architecture/plans/      — implementation plans
docs/runbooks/                — operational runbooks
docs/troubleshooting/         — troubleshooting guides
docs/lessons.md               — patterns learned, gotchas, post-mortems
CHANGELOG.md                  — project changelog
```

### Knowledge store (decide/position — NOT in this repo)

`10_projects/kubelab/` in the maintainer's vault holds strategic-only context: roadmap, tasks, `20-business/` (positioning, offers, funnel), portfolio, prestudy, and session memory.

### Task management conventions

- Every `[x]` MUST have a date: `✓ YYYY-MM-DD`
- Every `[!]` MUST reference blocker by task ID, not section name
- Completed tasks archived in `completed.md` (zero info loss)
- Product specs tracked in vault `10_projects/<product>/_index.md`
- Lessons that mature into critical gotchas → add to CLAUDE.md "Critical gotchas" section
