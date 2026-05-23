---
tags: [spec, verification]
created: "2026-05-13"
updated: "2026-05-21"
---

# Verification - AI-001-ollama-public

> Auth strategy resolved in [[adr-035-api-auth-strategy]]. Implementation spans 3 PRs (A docs, B infra, C impl). Evidence bucketed per PR.

## Evidence per PR

### PR-A — Specs & ADR

- [ ] ADR-035 file exists at `vault/30-architecture/adrs/adr-035-api-auth-strategy.md` → vault commit hash `<hash>`.
- [ ] `proposal.md` "Auth strategy — RESOLVED" section present → repo commit `<hash>`.
- [ ] `specs/AI-002-e2e-tests/` proposal + tasks + verification all filled (no skeleton placeholders) → repo commit `<hash>`.
- [ ] Vault `11-tasks.md` AI-001 entry annotated `(PR #NNN open)` → vault commit `<hash>`.

### PR-B — Toolkit + Ansible infra

- [ ] `traefik-api-key-middleware` v0.1.2 entry in `traefik-helmconfig.yaml.j2` `experimental.plugins` → commit `<hash>`.
- [ ] `apply_middleware_secrets(env, project_root)` implemented in `toolkit/features/k8s_secrets.py` (or sibling) → commit `<hash>`.
- [ ] `apps.services.ai.ollama.api_key` registered in `SECRET_CATALOG` → commit `<hash>`.
- [ ] `make apply-middleware-secrets ENV=x` Makefile target wraps the toolkit call → commit `<hash>`.
- [ ] Unit tests for the renderer (fixture SOPS dict → expected Middleware YAML) → test name `<name>`.
- [ ] Smoke: `make provision NODE=vps ENV=prod TAGS=k3s` re-templates HelmChartConfig; Traefik pods Healthy post-roll → kubectl output `<paste>`.
- [ ] CLAUDE.md gotcha "Middleware secret injection (X-API-Key plugin)" added.

### PR-C — K8s manifests + smoke

- [ ] Middleware template `infra/k8s/overlays/prod/middlewares/api-key-ollama.yaml.tpl` exists → commit `<hash>`.
- [ ] Prod overlay `patches.yaml` patches `ollama` IngressRoute to swap host + add api-key-ollama middleware → commit `<hash>`.
- [ ] SOPS entry `apps.services.ai.ollama.api_key` set (32-byte random, base64) → SOPS audit clean.
- [ ] Deploy run: `make apply-secrets ENV=prod && make apply-middleware-secrets ENV=prod && make deploy-k8s ENV=prod` exits 0.
- [ ] Cert: `kubectl get ingressroute ollama -n kubelab -o jsonpath='{.spec.tls.certResolver}'` returns `letsencrypt`.
- [ ] `curl https://ollama.kubelab.live/api/tags` returns 403 without auth → `<paste>`.
- [ ] `curl -H "X-API-Key: $KEY" https://ollama.kubelab.live/api/tags` returns 200 with model list → `<paste>`.
- [ ] `curl -H "Authorization: Bearer $KEY" https://ollama.kubelab.live/api/tags` returns 200 (Bearer mode works) → `<paste>`.
- [ ] `curl -X POST .../api/generate` streams inference → `<paste excerpt>`.
- [ ] Beelink/ace2 access logs show ZERO new lines for the unauthenticated probe (proof the middleware rejects before forwarding) → `<paste>`.
- [ ] LAN/Tailscale: `curl http://100.64.0.5:11434/api/tags` from ace1 returns 200 (unaffected) → `<paste>`.
- [ ] Prod E2E suite: `make test-e2e ENV=prod` zero regressions → CI run `<link>`.

## Decisions made during implementation

- **Auth choice locked**: X-API-Key via `dtomlinson91/traefik-api-key-middleware` v0.1.2+, both header forms (`X-API-Key` + `Authorization: Bearer`) enabled. Rationale: forward-compat with Stage 2 OIDC/JWT migration per ADR-035 (clients sending Bearer today work tomorrow with JWTs unchanged).
- **Middleware secret injection pattern**: extended toolkit (not Kustomize replacements / Helm) — keeps the SOPS path canonical and reusable for future plugins requiring inline secrets.
- Other non-obvious trade-offs: <fill at impl time>

## Promotion candidates

- [x] **ADR-worthy decision**: Yes — ADR-035 created. Anchored decisions table tracks AI-001 + future AI-004/DT-004.
- [ ] **Lesson** for `kubelab/lessons.md`: After PR-C, capture "Traefik plugin keys are inline-in-CRD; toolkit middleware-secret renderer is the reusable substitution path". Promote if other ops repeat the gotcha.
- [ ] **New pattern** for `00_meta/patterns/`: Likely yes — "API auth via per-service Traefik plugin Middleware + toolkit secret renderer" is the factory pattern under ADR-035. Promote after AI-004 confirms the pattern works in a second service.

## Archive checklist (post PR-C merge)

- [ ] `proposal.md` frontmatter → `status: archived`.
- [ ] `mv specs/AI-001-ollama-public/ → specs/archive/AI-001-ollama-public/`.
- [ ] Vault `11-tasks.md` AI-001 ticked with PR-A/B/C links.
- [ ] ADR-035 anchored decisions table: AI-001 row → "Live, Stage 1".
- [ ] Promotions executed.
