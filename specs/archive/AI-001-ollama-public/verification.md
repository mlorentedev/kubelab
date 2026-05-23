---
tags: [spec, verification]
created: "2026-05-13"
updated: "2026-05-23"
status: complete
---

# Verification - AI-001-ollama-public

> Auth strategy resolved in [[adr-035-api-auth-strategy]]. Implementation spanned 7 PRs over 2 sessions (2026-05-21 → 2026-05-23). All evidence captured below.

## PR ledger

| PR | Title | Merged | Scope |
|----|-------|--------|-------|
| #190 | docs(spec): AI-001 auth strategy resolved (ADR-035) + AI-002 e2e tests filled | 2026-05-22 | ADR-035 + specs |
| #191 | chore(spec): address Codex P1+P2 review on PR #190 (AI-001/AI-002) | 2026-05-22 | Spec corrections: prod IngressRoute drill removed (P1), 401→403 unified per plugin README (P2) |
| #192 | chore(spec): replace SOPS mutation drill with wrong-key E2E test (Codex P1 on PR #191) | 2026-05-23 | Spec: mutation drill via SOPS tampering replaced with hardcoded wrong-key sentinel (independent oracle) |
| #193 | feat(toolkit): apply-middleware-secrets for Traefik API-key Middlewares (AI-001 PR-B) | 2026-05-23 | Toolkit `k8s_middlewares.py` + Ansible plugin + Makefile + CLI + generic template + CLAUDE.md gotcha (~150 LOC, 14 tests 90% cov) |
| #194 | fix(secrets): seed ollama api_key in prod SOPS to unblock deploy-k8s (Codex P1 on #193) | 2026-05-23 | SOPS seed (Codex caught the apply-middleware-secrets chain blocking deploy-k8s) |
| #195 | feat(k8s): ollama public exposure on prod with X-API-Key auth (AI-001 PR-C) | 2026-05-23 | Prod IngressRoute patch + common.yaml SSOT placeholder |
| #196 | feat(dns): add ollama.kubelab.live A record (AI-001 follow-up) | 2026-05-23 | Terraform Cloudflare A record (proxied:false) |
| #197 | chore(homepage): refresh daily Cloudflare query date | 2026-05-23 | Incidental homepage drift refresh |
| #198 | feat(k8s): rate-limit + in-flight cap for ollama public endpoint (SEC-AI-001 MVP) | 2026-05-23 | Traefik `RateLimit` (60/min burst 10) + `InFlightReq` (cap 2) post-auth throttle |
| #199 | fix(ansible): ace2 ollama host networking + UFW (ANSIBLE-025) | 2026-05-23 | `network_mode: host` + UFW (Tailscale/LAN) — root-cause fix for tailscaled-flap induced container loop discovered during smoke |

Total ~400 LOC across infra + toolkit + Ansible + specs.

## Evidence per PR

### PR-A — Specs & ADR (#190 + #191 + #192)

- [x] ADR-035 file exists at vault `30-architecture/adrs/adr-035-api-auth-strategy.md` — anchored decisions table updated 2026-05-23 with AI-001 row → "Live, Stage 1".
- [x] `proposal.md` "Auth strategy — RESOLVED" section present.
- [x] `specs/AI-002-e2e-tests/` proposal + tasks + verification filled.
- [x] Vault `11-tasks.md` AI-001 entry tracks all PR links.
- [x] Codex P1+P2 follow-ups landed cleanly (3-iteration spec correction loop — atrapó bugs lógicos antes de tocar código prod).

### PR-B — Toolkit + Ansible infra (#193)

- [x] `dtomlinson91/traefik-api-key-middleware` v0.1.2 entry in `infra/ansible/roles/k3s_server/templates/traefik-helmconfig.yaml.j2` `experimental.plugins` (alongside CrowdSec `bouncer:`).
- [x] `apply_middleware_secrets(env, project_root)` implemented in **new sibling module** `toolkit/features/k8s_middlewares.py` (NOT `k8s_secrets.py` — separated registries to prevent naming drift when DT-004/AI-004 adopt the pattern).
- [x] `apps.services.ai.ollama.api_key` registered in `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`) with `kind=RANDOM_TOKEN, length=32, envs=("prod",)`.
- [x] `make apply-middleware-secrets ENV=x` Makefile target wraps the toolkit call. Wired into `make deploy-k8s` chain (after `apply-secrets`, before `validate-sync`).
- [x] CLI command: `tk infra k8s apply-middleware-secrets --env <env> [--dry-run]`.
- [x] 14 unit tests covering: catalog invariants, pure render substitution, kubectl-apply integration (mocked), audit-copy write, dry-run, missing-template + missing-SOPS-key failure modes. 90% coverage of `k8s_middlewares.py`.
- [x] Smoke `make apply-middleware-secrets ENV=staging` → no-op exit 0 ("no middlewares for env=staging") — kubectl never invoked. Pre-flight validation works.
- [x] Smoke `make provision NODE=vps ENV=prod TAGS=k3s` (2026-05-23, deferred from PR-B closing): HelmChartConfig re-templated with `api-key:` plugin entry; `kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik` shows fresh pod (`traefik-7dd8b47b96-psh64 Running 4m21s`). HelmChartConfig spec confirmed via `kubectl get helmchartconfig -n kube-system traefik -o yaml` — both `bouncer:` and `api-key:` plugins registered. **One false-positive surfaced**: playbook task "Verify K3s Traefik is listening on Pattern C ports 8080/8443" times out — Pattern C cutover happened months ago (prod uses 80/443). Captured as **ANSIBLE-024** (separate ticket, did NOT block deploy).
- [x] CLAUDE.md gotcha "Middleware secret injection (ADR-035 Stage 1, AI-001)" added — explains the SOPS → render → audit → kubectl-apply stdin flow.

### PR-C — K8s manifests + SOPS + smoke (#194 + #195 + #196)

- [x] Generic Middleware template `infra/k8s/overlays/prod/middlewares/api-key.yaml.tpl` (created in PR-B, reused as-is per spec design).
- [x] Prod overlay `patches.yaml`: ollama IngressRoute host `ollama.staging.kubelab.live` → `ollama.kubelab.live`; middlewares `[secure-headers, crowdsec-bouncer, api-key-ollama, error-pages]`; certResolver `letsencrypt`.
- [x] `infra/config/values/common.yaml`: `api_key: secrets://apps.services.ai.ollama.api_key` self-documenting placeholder added to `apps.services.ai.ollama`.
- [x] SOPS: `apps.services.ai.ollama.api_key` seeded in `prod.enc.yaml` (#194 — 32-byte urlsafe random via `toolkit secrets set`).
- [x] Deploy chain executed 2026-05-23 on prod kubeconfig: `make apply-secrets ENV=prod && make apply-middleware-secrets ENV=prod && make deploy-k8s ENV=prod` → 41 K8s resources `configured`, 0 failed. Argo CD `kubelab-prod` `Synced Healthy` rev `b19d9f5` matching master HEAD.
- [x] Cert provisioned: `kubectl get ingressroute ollama -n kubelab -o jsonpath='{.spec.tls.certResolver}'` = `letsencrypt`. Cert wildcard `kubelab.live` (catch-all) — Let's Encrypt R13, subject CN=`kubelab.live`, expires 2026-08-21.
- [x] Cloudflare DNS A record created via Terraform (#196): `dig +short ollama.kubelab.live A` → `162.55.57.175` (VPS public IP, proxied:false).
- [x] **Smoke trio post-hardening** (#199 + curls 2026-05-23):
  ```
  no-auth:   HTTP 403
  X-API-Key: HTTP 200  (+ models list: qwen2.5:7b, qwen2.5-coder:7b)
  Bearer:    HTTP 200
  wrong-key: HTTP 403
  ```
- [x] **Inference test** via `/api/generate`:
  ```
  POST -d '{"model":"qwen2.5-coder:7b","prompt":"print hello in python","num_predict":15}'
  -H "X-API-Key: $KEY"
  → HTTP 200 (23s, 5.2 tok/s CPU)
  Response: 'Printing "hello" in Python is straightforward. You can use the `print'
  ```
- [x] LAN/Tailscale path unaffected: `curl http://100.64.0.5:11434/api/tags` from msi workstation → 200.

### SEC-AI-001 MVP — RateLimit + InFlightReq (#198)

- [x] Both Middleware CRDs live in `kubelab` namespace: `ollama-ratelimit` (average=60 period=1m burst=10 ipStrategy.depth=1) + `ollama-inflight` (amount=2 ipStrategy.depth=1).
- [x] IngressRoute middleware chain order: `[secure-headers, crowdsec-bouncer, api-key-ollama, ollama-ratelimit, ollama-inflight, error-pages]`. Auth FIRST so unauth requests die in 403 before consuming per-IP quota.
- [x] Burst test 2026-05-23: 15 simultaneous X-API-Key'd requests → `2 × 200 + 13 × 429`. Rate-limit fires. After 90s cooldown: single request → 200 (bucket refilled).

### ANSIBLE-025 — ace2 host networking (#199)

- [x] Root cause confirmed live during smoke: `dockerd: failed to bind host port 100.64.0.5:11434/tcp: cannot assign requested address` — tailscale0 flapped, IP-specific bind became unassignable, container loop until manual recreate.
- [x] Fix: `network_mode: host` + UFW (allow from `tailscale_cidr` + `lan_cidr`, default-deny inherited from `base_system` role). Compose template + tasks updated in `ace2_services` role.
- [x] Provision verified: `ss -ltnp | grep 11434` = `LISTEN *:11434 ollama` (was `dockerd 100.64.0.5:11434`). UFW rules present. Smoke trio + rate-limit still pass post-fix.

## Decisions made during implementation (lessons crystallized)

- **k8s_middlewares.py as sibling module** (not folded into k8s_secrets.py): K8s native Secrets vs Traefik CRDs have different lifecycle + registry. Separation prevents naming drift when DT-004/AI-004 adopt the pattern.
- **kubectl-apply via stdin, NOT Kustomize** for Middlewares carrying plaintext keys: committed plaintext = no-go, gitignored `generated/` dir = ARGO-007 conflict (Argo CD reads from Git). Render → audit copy in `.rendered/` (gitignored) → `apply -f -` via stdin. Plaintext never persists outside the gitignored audit dir.
- **Generic template** (`api-key.yaml.tpl`) substituting `${NAME}/${SERVICE}/${API_KEY}` per `MiddlewareSpec`, reusable across services. One template, infinite services.
- **Mutation testing requires independent oracle** (caught by Codex on #191): a mutation drill where both actor (client fixture) and target (middleware) read the same SOPS file is NOT a mutation — coordinated rotation is invariant. The fix (PR #192) was a hardcoded wrong-key sentinel that breaks the coupling at zero cost. Pattern candidate for `00_meta/patterns/`.
- **3-iteration spec correction loop validated**: PR #190 → Codex P1+P2 → PR #191 → Codex P1 → PR #192 → PR #193 implementation. The loop atrapó bugs lógicos antes de tocar código de producción. Costó 2-3 min CI por iteración; ganaría 30+ min de descubrimiento post-implementation.
- **`enable_auth: false` deliberately preserved for ollama in common.yaml** even after auth was added: the field's semantics in this repo are Authelia-scoped. Plugin auth is not Authelia auth. Flipping it would create misleading SSOT (the generators would add ollama to Authelia access_control rules — irrelevant since prod's configuration.yml is hardcoded inline).
- **`secrets://` scheme in common.yaml is documentation-only** (mirrored from CrowdSec `bouncer_api_key`): no code parses it. Self-documenting hint that the value lives in SOPS.
- **Hardcoded IP binds in compose are a fragility footgun**: `ports: ["{tailscale_ip}:11434:11434"]` binds to a specific interface IP; Linux does NOT auto-rebind after interface flap. `network_mode: host` + UFW is the resilient pattern. Promoted to vault `90-lessons.md` candidate.

## Promotion candidates (executed)

- [x] **ADR-035** crystallized — anchored decisions table maintained.
- [x] **Lesson**: "Middleware secret injection via toolkit + plugin Middleware CRD" pattern captured as CLAUDE.md critical gotcha. Will be reused by DT-004 (widget-proxy) + AI-004 (Pollex public) + future AI services per ADR-035.
- [x] **Runbook**: vault `40-runbooks/ollama-api-key-rotation.md` — covers generate, apply, smoke verify, rollback, distribute, what-not-to-do.
- [ ] **Pattern candidate**: "API auth via per-service Traefik plugin Middleware + toolkit secret renderer" → `00_meta/patterns/`. Defer to AI-004 (Pollex) to confirm reuse before promoting.
- [ ] **Pattern candidate**: "Independent oracle for mutation drills" → `00_meta/patterns/`. Defer to second observation.

## Discovered tickets (during implementation/smoke)

- **ANSIBLE-024**: provision-vps.yml stale Pattern C ports verification (false-positive post-cutover). Captured.
- **ANSIBLE-025**: ace2 ollama compose race-condition with tailscaled. **CLOSED by #199 in this PR set.**
- **DASH-DT-010**: homepage Cloudflare query `date_gt` drifts daily (template root cause). Captured + band-aid via #197.
- **SEC-AI-001**: post-auth abuse protection. **MVP delivered as #198**; full follow-ups (multi-key, custom CrowdSec scenario, prompt-size limit) captured.
- **SEC-AI-002**: `kubectl apply --server-side` to eliminate Middleware `last-applied-configuration` annotation leak. Captured.
- **WEBUI-001**: connect OpenClaw on Beelink to the public ollama endpoint. Captured.

## Archive checklist

- [x] `proposal.md` frontmatter → `status: archived` + `archived: "2026-05-23"`.
- [x] `mv specs/AI-001-ollama-public/ → specs/archive/AI-001-ollama-public/`.
- [x] Vault `11-tasks.md` AI-001 entry annotated with all PR links.
- [x] ADR-035 anchored decisions table updated → "Live 2026-05-23".
- [x] Runbook published.
- [x] Promotions executed (CLAUDE.md gotcha + ADR + runbook).
