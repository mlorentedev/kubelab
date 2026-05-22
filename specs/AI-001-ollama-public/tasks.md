---
tags: [spec, tasks]
created: "2026-05-13"
updated: "2026-05-21"
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
- [ ] Commit + push + PR. Tag in vault `11-tasks.md` AI-001 entry.

## PR-B — Toolkit + Ansible infra prep (~150 LOC)

> Merges after PR-A. No K8s manifest changes yet — purely the plumbing.

- [ ] Branch: `feat/ai-001-toolkit-middleware-secrets` from PR-A merged master.
- [ ] Ansible: add `traefik-api-key-middleware` to `infra/ansible/roles/k3s_server/templates/traefik-helmconfig.yaml.j2` `experimental.plugins` alongside the existing `bouncer:` (CrowdSec) entry.
- [ ] Toolkit: extend `toolkit/features/k8s_secrets.py` (or a new sibling `k8s_middlewares.py`) with `apply_middleware_secrets(env, project_root)` that:
  - Reads SOPS `apps.services.<service>.api_key` for each registered service.
  - Renders a Middleware CRD from a template (`infra/k8s/overlays/<env>/middlewares/api-key-<service>.yaml.tpl`) substituting `${API_KEY}`.
  - Writes to `infra/k8s/overlays/<env>/generated/middlewares/` (gitignored).
- [ ] Toolkit: register `apps.services.ai.ollama.api_key` in `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`).
- [ ] Makefile: new target `make apply-middleware-secrets ENV=x` wrapping the toolkit call. Wire into `make deploy-k8s` if appropriate.
- [ ] Unit tests for the new toolkit function (fixture: fake SOPS dict → expected Middleware YAML).
- [ ] Smoke: `make provision NODE=vps ENV=prod TAGS=k3s` re-templates the HelmChartConfig with the new plugin entry; verify `kubectl get pods -n kube-system traefik-*` healthy.
- [ ] Commit + push + PR. CLAUDE.md gotcha for "Middleware secret injection" added.

## PR-C — K8s manifests + SOPS + smoke (~100 LOC)

> Merges after PR-B. Actual public-exposure activation.

- [ ] Branch: `feat/ai-001-ollama-public-impl` from PR-B merged master.
- [ ] Middleware template: `infra/k8s/overlays/prod/middlewares/api-key-ollama.yaml.tpl` with `keys: [${API_KEY}]`, `removeHeadersOnSuccess: true`, both header forms enabled.
- [ ] Prod overlay `patches.yaml`: add patch for the `ollama` IngressRoute (base) to override host to `ollama.kubelab.live` and append the `api-key-ollama` middleware ref.
- [ ] `infra/config/values/common.yaml`: confirm `apps.services.ai.ollama.api_key` placeholder path (real value lives in SOPS only).
- [ ] SOPS: `make secrets ENV=common` → add `apps.services.ai.ollama.api_key` (32-byte random key, base64).
- [ ] Deploy: `make apply-secrets ENV=prod` → `make apply-middleware-secrets ENV=prod` → `make deploy-k8s ENV=prod`.
- [ ] Verify cert: `kubectl get ingressroute ollama -n kubelab -o yaml | grep certResolver` returns `letsencrypt`.
- [ ] Smoke (acceptance criteria):
  - `curl https://ollama.kubelab.live/api/tags` → 403 (no auth).
  - `curl -H "X-API-Key: $KEY" https://ollama.kubelab.live/api/tags` → 200 + model list.
  - `curl -H "Authorization: Bearer $KEY" https://ollama.kubelab.live/api/tags` → 200 (Bearer mode works too, forward-compat for Stage 2).
  - `curl -X POST -d '{"model":"...","prompt":"..."}' -H "X-API-Key: $KEY" https://ollama.kubelab.live/api/generate` → streams inference.
- [ ] E2E test added under `tests/e2e/` exercising the 403/200 boundary (consumes AI-002 spec).
- [ ] Existing prod E2E suite passes (zero regressions).
- [ ] LAN/Tailscale path unaffected: `curl http://100.64.0.5:11434/api/tags` from any Tailscale node still works.

## Closing (post PR-C merge)

- [ ] All acceptance criteria from `proposal.md` covered by E2E test or smoke output documented in `verification.md`.
- [ ] Kustomize build clean: `kubectl kustomize infra/k8s/overlays/prod/ | grep -i 'api-key'` shows the rendered Middleware.
- [ ] PR-A/B/C all merged. AI-001 ticked in vault `11-tasks.md` with all three PR links.
- [ ] ADR-035 anchored decisions table updated with AI-001 status → "Live, Stage 1".
- [ ] `specs/AI-001-ollama-public/` archived: `mv specs/AI-001-ollama-public/ specs/archive/AI-001-ollama-public/`.
- [ ] Rotate plan documented in vault `40-runbooks/`: how to rotate Ollama API key (regen + SOPS edit + `make apply-middleware-secrets` + curl smoke).
