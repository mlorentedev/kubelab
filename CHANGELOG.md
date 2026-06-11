# KubeLab — Changelog

Significant changes to the KubeLab platform, tracked independently from git history. Focus on **what changed and why**, not individual commits.

## Format

```
## YYYY-MM-DD

### Added / Changed / Fixed / Removed

- Description of the change and why it was made
```

## 2026-03-26

### Changed

- **SEC-003: CrowdSec bouncer migrated to native Traefik plugin** — Replaced deprecated `fbonalair/traefik-crowdsec-bouncer` (ForwardAuth sidecar) with `maxlerebourg/crowdsec-bouncer-traefik-plugin` v1.5.1. No separate bouncer pod. Plugin registered in HelmChartConfig, API key via volume-mounted Secret in `kube-system`. Stream mode (60s LAPI poll). `ClientTrustedIPs` whitelists Tailscale CIDR.

### Added

- **`SecretMapping.namespace` field** — `k8s_secrets.py` now supports cross-namespace secrets. `crowdsec-bouncer-traefik` Secret created in `kube-system` for Traefik volume mount.

### Removed

- **`crowdsec-bouncer` Deployment + Service** — ForwardAuth sidecar replaced by in-process Traefik plugin. Saves ~64Mi memory and one pod.

### Fixed

- **aws1 Spot instance restore** — Instance was unreachable after AWS stop/start cycle (SSH hung, Tailscale offline). Root cause: `#cloud-config` not on first line (yamllint comment broke detection), plus `UseDNS yes` causing SSH reverse DNS timeout.
- **cloud-init node recycling** — Added Headscale API call to delete stale node before Tailscale registration. Prevents hostname collision and IP duplication on Spot replacement.
- **MagicDNS for aws1 (ADR-025, closes INTERNAL-001)** — Replaced hardcoded `tailscale_ip: 100.64.0.4` with `tailscale_dns: aws1.kubelab.internal`. Changed Headscale `base_domain` from `kubelab.vpn` (fake TLD) to `kubelab.internal` (IANA-reserved `.internal` TLD). Kubeconfig and K3s TLS SAN use DNS name. IP changes on Spot replacement no longer require manual updates.
- **Makefile inline scripts → toolkit** — Extracted SOPS→tfvars generation from inline Python in Makefile to `toolkit infra terraform aws-tfvars` command.

## 2026-03-25

### Added

- **IMMUTABLE_SECRETS protection** — `credentials.py` preserves storage_encryption_key, session_secret, jwt_secret, oidc_hmac_secret from existing SOPS during credential regeneration. Prevents Authelia DB corruption.
- **SSOT `apps.auth.admin_username: manu`** — single source for admin identity across all services (Authelia, Grafana, MinIO, Gitea, Traefik basic_auth). `credentials.py` reads as default.
- **SSOT `networking.vpn_extra_records`** — Headscale extra_records moved from hardcoded playbook to common.yaml. deploy-vps.yml consumes via loop.
- **SSOT `networking.trusted_cidrs`** — Authelia access_control networks from common.yaml (RFC1918 + Tailscale). Replaces hardcoded CIDRs in template.
- **Gitea bootstrap ConfigMap** — postStart script handles admin user creation, admin→manu migration (SQLite), and OIDC provider registration. All idempotent.
- **Gitea OIDC via postStart** — OIDC client secret added to `gitea-secrets` K8s Secret. Discovery URL from ConfigMap (env-specific). No more manual `configure_oidc.py` runs.

### Changed

- **CrowdSec bouncer key generation** — replaced imperative `docker exec cscli bouncers add` (95 lines) with declarative `secrets.token_urlsafe(32)`. Both LAPI and bouncer read from same K8s Secret. No Docker dependency for credential generation.
- **CrowdSec postStart hook** — idempotent delete+add, explicit failure on LAPI timeout (no more `|| true` error swallowing).
- **Authelia admin user** — renamed from `admin` to `manu` in common.yaml users list. Dynamic `users_{username}_password_hash` key in SOPS.
- **`middlewares.yml.j2`** — fixed dead `APP_NGINX_NAME` reference to `EDGE_ERRORS_NAME`.
- **Wiki generator** — graceful WARNING when template not found (was ERROR, failed pipeline).

### Discovered

- **CrowdSec bouncer `fbonalair/traefik-crowdsec-bouncer` is deprecated** — produces empty logs, fails to authenticate with LAPI after restarts. Replacement: `maxlerebourg/crowdsec-bouncer-traefik-plugin` (native Traefik plugin). Filed as SEC-003.

## 2026-03-22

### Added

- **ADR-024: PVC Backup Strategy** — CronJob + tar + sqlite3 .backup + MinIO. Prod overlay only. 7-day retention, daily at 03:00 UTC
- **PVC backup-restore runbook** (`40-runbooks/pvc-backup-restore.md`) — procedures for backup verification, single-PVC restore, full DR restore
- **Security headers on ALL prod IngressRoutes** — CSP, HSTS, X-Frame-Options, X-Content-Type-Options applied uniformly
- **CoreDNS hairpin DNS for prod** — rewrite approach for prod domains resolving inside K3s cluster
- **n8n `enableServiceLinks: false`** — prevents K8s N8N_PORT injection (same pattern as Authelia)
- **Gitea OIDC on prod** — configure_oidc.py updated to use update-oauth for idempotency
- **Gitea admin_password + OIDC secrets** added to prod SOPS
- **TOOL-001/TOOL-002 backlog items** — secret drift detection and cross-env sync automation
- **PROD-K3S-007..010** — post-cutover verification tasks (ForwardAuth, dashboard, error-pages, staging DNS)

### Changed

- **PROD-K3S-003b COMPLETE**: Port swap prod.yaml 8080/8443 → 80/443, Ansible deployed HelmChartConfig, Docker Compose Traefik stopped on VPS
- **Ansible inventory**: VPS now in `k3s_servers` group for prod (was ace1 only)
- **configure_oidc.py**: uses `update-oauth` instead of delete+add-oauth (preserves user linkages)
- **Traefik HelmChartConfig**: `port=exposedPort` for clean HTTP→HTTPS redirects
- **Traefik dashboard**: enabled via `additionalArguments` (not api.dashboard values)

### Fixed

- **Grafana OIDC URLs in prod overlay** — pointed to correct external Authelia URL
- **HTTP→HTTPS redirect** — fixed by matching port and exposedPort in HelmChartConfig
- **n8n basic_auth fallback** — caused by K8s service env var injection (`N8N_PORT=tcp://...`)
- **Authelia ForwardAuth 403 loop** — browser caching basic_auth credentials; fix: authRequestHeaders whitelist
- **E2E prod**: 53 passed, 0 failed (down from 7 failures)

## 2026-02-24

### Added

- **Authelia 4.39.15** deployed on K3s staging (STAGE-006b): ForwardAuth, file-based auth, Redis sessions, TOTP/WebAuthn, SMTP notifier
- **Authelia custom branding**: KubeLab hexagon K logo (indigo/cyan gradient) + favicon, served via `server.asset_path`
- **SOPS + age secrets pipeline**: `tk infra k8s apply-secrets` creates authelia-secrets, authelia-users, grafana-admin from encrypted values
- **`k8s_secrets.py`**: new toolkit module for K8s secret management (create, apply, validate)
- **ForwardAuth middleware** wired to protected IngressRoutes: grafana and loki require Authelia login (STAGE-006c)
- **IngressRoutes declared in Git**: authelia, grafana, loki, catch-all (previously manual kubectl)
- **Grafana proxy auth**: SSO via Authelia `Remote-User` header — single login, no double auth
- **`authelia-assets` ConfigMap**: via kustomize `configMapGenerator` (same pattern as `grafana-dashboards`)

### Changed

- `CLAUDE.md`: 4 new critical gotchas (Authelia service links, binary assets, toolkit deploy, key paths)
- `staging.yaml`: added `disable_require_tls: false` for AutheliaGenerator template
- `kustomization.yaml`: added authelia resource + authelia-assets configMapGenerator
- Staging overlay `ingress.yaml`: platform app IngressRoutes (api, web, blog) now overlay-only

### Fixed

- **Secrets key path mismatch**: `_print_secrets_for_manual_copy()` used `apps.authelia.*` instead of `apps.services.security.authelia.*`
- **Authelia K8s crash**: `enableServiceLinks: false` to prevent K8s `AUTHELIA_*` env var injection conflicting with config
- **Authelia rootfs mount failure**: `automountServiceAccountToken: false` (read-only `/run` in image)
- **Encrypted secrets structure**: `dev.enc.yaml` and `staging.enc.yaml` now use correct nested key paths

## 2026-02-21

### Added

- Headscale VPN mesh operational: 9 nodes connected (VPS + homelab + workstation)
- Headscale v0.28.0 deployed on VPS (`/opt/headscale/`, Docker Compose, `proxy` network)
- Traefik dynamic route `app-headscale.yml` on VPS for `vpn.kubelab.live`
- Let's Encrypt cert for `vpn.kubelab.live` via DNS challenge (Cloudflare)
- K8s manifest generator (`K8sGenerator`) added to toolkit — generates Kustomize-structured manifests for platform apps (api, web, blog)
- 5 Jinja2 templates: `infra/k8s/templates/{kustomization,deployments,services,configmaps,ingress}.yaml.j2`
- Automation tasks added: ANSIBLE-006 (Headscale provisioning), ANSIBLE-007 (Traefik routes)

### Changed

- Cloudflare API token updated to include both zones (`mlorente.dev` + `kubelab.live`)
- `vpn.kubelab.live` DNS set to DNS-only (grey cloud) — required for WireGuard/DERP
- Vault runbook `headscale-setup.md` fully rewritten with actual IPs, gotchas, troubleshooting
- Vault `hardware/00-context.md` updated with actual Headscale IPs (100.64.0.x)
- `common.yaml`: added `use_local_certs: false` default to `edge.traefik` (was only in dev.yaml)

### Fixed

- VPS `traefik.yml` ACME storage path: corrected to `/letsencrypt/acme.json` (was overwritten with `/etc/traefik/acme/`)

## 2026-02-08

### Added

- Vault structure created: ADRs, runbooks (9), troubleshooting (16 categories), hardware docs
- Migrated operational docs from repo `docs/` to vault (source of truth)
- Cubernautas blog/newsletter content moved under KubeLab project

### Changed

- Repo `docs/TROUBLESHOOTING.md`, `docs/HOW-TO.md`, `docs/KUBELAB.md` replaced with lightweight pointers to vault
- `CLAUDE.md` and `GEMINI.md` updated with vault routing rules
