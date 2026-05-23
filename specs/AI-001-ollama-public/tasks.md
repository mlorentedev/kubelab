---
tags: [spec, tasks]
created: "2026-05-13"
updated: "2026-05-23"
---

# Tasks - AI-001-ollama-public

> Auth decision resolved 2026-05-21 in [[adr-035-api-auth-strategy]] — X-API-Key via Traefik plugin `dtomlinson91/traefik-api-key-middleware` v0.1.2+. Implementation split into 3 atomic PRs (linear deps).

## Setup

- [x] Branch created: `feat/ai-001-ollama-public-auth` (worktree at `.worktrees/ai-001-ollama-public`).
- [x] `proposal.md` complete and acceptance criteria testable.
- [x] **Decision finalized:** X-API-Key plugin per ADR-035 (Stage 1; Stage 2 = OIDC client_credentials when kubelab-agents L1 lands).
- [x] No open questions left in `proposal.md` "Risks / open questions".

## PR-A — Specs & ADR (docs only, ~80 LOC)

> First merge. Paves the architecture before any code lands.

- [x] Write ADR-035 to vault (`30-architecture/adrs/adr-035-api-auth-strategy.md`).
- [x] Update `proposal.md`: auth decision resolved, 3-PR split documented.
- [x] Update `tasks.md` (this file): rewrite into 3-PR structure.
- [x] Update `verification.md`: evidence buckets restructured per PR scope.
- [x] Fill `specs/AI-002-e2e-tests/` skeleton (E2E coverage for Ollama health + auth).
- [x] Commit + push + PR. Tag in vault `11-tasks.md` AI-001 entry. → PR #190 merged 2026-05-22.
- [x] (Follow-up) Address Codex P1+P2 review on PR #190 (auth-regression drill → SOPS-tampering mutation; unify 401→403 per plugin README). → PR #191 merged 2026-05-23.

## PR-B — Toolkit + Ansible infra prep (~150 LOC)

> Merges after PR-A. No K8s manifest changes yet — purely the plumbing.

- [x] Branch: `feat/ai-001-toolkit-middleware-secrets` from PR-A merged master.
- [x] Ansible: add `api-key:` plugin (`github.com/dtomlinson91/traefik-api-key-middleware` v0.1.2) to `infra/ansible/roles/k3s_server/templates/traefik-helmconfig.yaml.j2` `experimental.plugins` alongside the existing `bouncer:` (CrowdSec) entry.
- [x] Toolkit: new sibling module `toolkit/features/k8s_middlewares.py` with `apply_middleware_secrets(env, project_root, dry_run)` that:
  - Reads SOPS `apps.services.<service>.api_key` via new `ConfigurationManager.get_secret_by_path()` (symmetric counterpart of `_set_nested_key`).
  - Renders a Middleware CRD from a generic template `infra/k8s/overlays/<env>/middlewares/api-key.yaml.tpl` substituting `${NAME}` / `${NAMESPACE}` / `${SERVICE}` / `${API_KEY}` (one template, reusable across services).
  - Writes audit copy to `infra/k8s/overlays/<env>/middlewares/.rendered/` (gitignored; NOT `generated/` — that path is committed for ArgoCD per ARGO-007, would leak plaintext).
  - Applies via `kubectl apply -f -` (stdin) — plaintext never persists outside the gitignored audit copy.
- [x] Toolkit: register `apps.services.ai.ollama.api_key` in `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`) with `kind=RANDOM_TOKEN`, `envs=("prod",)`.
- [x] Makefile: new target `make apply-middleware-secrets ENV=x` wrapping the toolkit call. Wired into `make deploy-k8s` (runs after `apply-secrets`).
- [x] CLI: new command `tk infra k8s apply-middleware-secrets --env <env> [--dry-run]`.
- [x] Unit tests for the new toolkit function (14 tests, 90% coverage of `k8s_middlewares.py`) — catalog invariants, pure render substitution, kubectl-apply integration (mocked), audit-copy write, dry-run, missing-template + missing-SOPS-key failure modes.
- [x] Smoke `make apply-middleware-secrets ENV=staging` → no-op exit 0 ("no middlewares for env=staging"), kubectl never invoked.
- [ ] Smoke `make provision NODE=vps ENV=prod TAGS=k3s` re-templates the HelmChartConfig with the new plugin entry; verify `kubectl get pods -n kube-system traefik-*` healthy. **(Deferred to PR-C closing — requires homelab on + prod kubeconfig)**
- [x] CLAUDE.md gotcha for "Middleware secret injection (ADR-035 Stage 1, AI-001)" added.
- [x] Commit + push + PR. → PR #193 merged 2026-05-23.
- [x] (Follow-up) Codex P1 on PR #193: `apply-middleware-secrets` blocked `deploy-k8s ENV=prod` because SOPS key was deferred to PR-C. Fixed by seeding `apps.services.ai.ollama.api_key` in `prod.enc.yaml`. → PR #194.

## PR-C — K8s manifests + SOPS + smoke (~100 LOC)

> Merges after PR-B + #194. Actual public-exposure activation.

- [x] Branch: `feat/ai-001-ollama-public-impl` stacked on `fix/ai-001-seed-ollama-api-key` (#194). Rebases cleanly on master once #194 squashes in.
- [x] ~~Middleware template `infra/k8s/overlays/prod/middlewares/api-key-ollama.yaml.tpl`~~ → already created in PR-B as generic `api-key.yaml.tpl` (substitutes `${NAME}` / `${SERVICE}` per MiddlewareSpec; one template reused across services). PR-C consumes it as-is.
- [x] Prod overlay `patches.yaml`: added patch for the `ollama` IngressRoute (base) overriding host to `ollama.kubelab.live` and appending the `api-key-ollama` middleware ref. Verified via `kubectl kustomize`: route renders with `[secure-headers, crowdsec-bouncer, api-key-ollama, error-pages]` and `api-key-ollama` Middleware CRD is NOT in the kustomize output (per design — applied out-of-band by `apply-middleware-secrets`).
- [x] `infra/config/values/common.yaml`: added `api_key: secrets://apps.services.ai.ollama.api_key` to `apps.services.ai.ollama` (mirrors the crowdsec `bouncer_api_key` SSOT convention; documentation-only — no code consumes the `secrets://` scheme).
- [x] SOPS: `apps.services.ai.ollama.api_key` seeded in `prod.enc.yaml` (32-byte urlsafe random token via `toolkit secrets set`). Shipped in #194.
- [ ] Deploy: `make apply-secrets ENV=prod` → `make apply-middleware-secrets ENV=prod` → `make deploy-k8s ENV=prod`. **(Deferred — requires homelab + prod kubeconfig.)**
- [ ] Verify cert: `kubectl get ingressroute ollama -n kubelab -o yaml | grep certResolver` returns `letsencrypt`. **(Deferred — homelab session.)**
- [ ] Smoke (acceptance criteria) — **(Deferred — homelab session.)**:
  - `curl https://ollama.kubelab.live/api/tags` → 403 (no auth).
  - `curl -H "X-API-Key: $KEY" https://ollama.kubelab.live/api/tags` → 200 + model list.
  - `curl -H "Authorization: Bearer $KEY" https://ollama.kubelab.live/api/tags` → 200 (Bearer mode works too, forward-compat for Stage 2).
  - `curl -X POST -d '{"model":"...","prompt":"..."}' -H "X-API-Key: $KEY" https://ollama.kubelab.live/api/generate` → streams inference.
- [ ] E2E test added under `tests/e2e/` exercising the 403/200 boundary (consumes AI-002 spec). **(Deferred to AI-002 PR.)**
- [ ] Existing prod E2E suite passes (zero regressions). **(Deferred — homelab session.)**
- [ ] LAN/Tailscale path unaffected: `curl http://100.64.0.5:11434/api/tags` from any Tailscale node still works. **(Deferred — homelab session.)**

## Closing (post PR-C merge)

- [ ] All acceptance criteria from `proposal.md` covered by E2E test or smoke output documented in `verification.md`.
- [ ] Kustomize build clean: `kubectl kustomize infra/k8s/overlays/prod/ | grep -i 'api-key'` shows the rendered Middleware.
- [ ] PR-A/B/C all merged. AI-001 ticked in vault `11-tasks.md` with all three PR links.
- [ ] ADR-035 anchored decisions table updated with AI-001 status → "Live, Stage 1".
- [ ] `specs/AI-001-ollama-public/` archived: `mv specs/AI-001-ollama-public/ specs/archive/AI-001-ollama-public/`.
- [ ] Rotate plan documented in vault `40-runbooks/`: how to rotate Ollama API key (regen + SOPS edit + `make apply-middleware-secrets` + curl smoke).
