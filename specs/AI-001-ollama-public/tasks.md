---
tags: [spec, tasks]
created: "2026-05-13"
---

# Tasks - AI-001-ollama-public

> TDD order. One task = one focused commit.

## Setup

- [ ] Branch created from main: `feat/AI-001-ollama-public`
- [ ] `proposal.md` complete and acceptance criteria testable
- [ ] **Decision finalized:** auth strategy (BasicAuth | Authelia | custom header). Document choice in `proposal.md` and add one-line rationale.
- [ ] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

- [ ] Write failing E2E test: `ollama.kubelab.live/api/tags` returns 401 without auth
- [ ] Write failing E2E test: same endpoint returns 200 with correct auth
- [ ] Create Traefik middleware manifest for chosen auth strategy (in `apps/ollama/` or shared `infra/middleware/`)
- [ ] Add middleware secret to SOPS: `apps.services.ollama.api_key` in `common.enc.yaml`
- [ ] Create `IngressRoute` manifest for `ollama.kubelab.live` referencing the middleware
- [ ] Update prod values.yaml: enable ollama IngressRoute under prod overlay
- [ ] Deploy to staging first; verify both E2E tests pass against staging
- [ ] Refactor: extract reusable middleware if more AI services will use it (AI-004 Jetson)
- [ ] Deploy to prod via existing Argo CD / Ansible pipeline
- [ ] Verify cert provisioned in prod (Traefik dashboard or `kubectl get ingressroute`)

## Closing

- [ ] All acceptance criteria from `proposal.md` covered by at least one E2E test or smoke check
- [ ] Helm/Kustomize lint pass
- [ ] No unrelated changes in diff (scope creep guard)
- [ ] `verification.md` filled in
- [ ] PR opened referencing `specs/AI-001-ollama-public/`
- [ ] AI-001 ticked in `kubelab/11-tasks.md` with PR link
