---
tags: [spec, tasks]
---

# Tasks - TOOL-009-n8n-workflow-import

> TDD order. Implementation rides the notify branch after TOOL-008 (#104) merges + notify rebases
> (needs the `webhook_secret` catalog entry).

## Setup

- [x] Issue gate: mlorentedev/knowledge#108 (created via `gh api` REST — `gh issue create` uses GraphQL, which was rate-limited)
- [x] `proposal.md` complete; acceptance criteria testable
- [ ] Add #108 to the Bitácora Project board (deferred — needs GraphQL; verify whether auto-add already did it)
- [ ] Confirm n8n 2.12 `import:credentials` JSON shape for `httpHeaderAuth` (docs/CLI)

## Implementation

- [ ] Fix credential id in `notify-router.json` (`REPLACE_ON_IMPORT` → stable UUID)
- [ ] Failing test: credential JSON render reads `webhook_secret` from SOPS + id from the workflow JSON
- [ ] Failing test: command assembly (import:credentials via `/dev/shm`, import:workflow, update:workflow --active)
- [ ] Failing test: missing `webhook_secret` → clear error, no partial import
- [ ] Implement `toolkit/features/n8n_import.py` (render + exec assembly + idempotency)
- [ ] Wire CLI: new `n8n` subgroup under `infra` → `toolkit infra n8n import --env <e>`
- [ ] Add `infra/n8n/workflows/credentials/notify-webhook.json.tpl`
- [ ] Makefile: `import-n8n` target + hook into `deploy-k8s`
- [ ] Refactor: reuse a SOPS-render helper from `k8s_middlewares.apply_middleware_secrets` if shared

## Closing

- [ ] Every acceptance criterion covered by ≥1 test; `make test` green
- [ ] `features.json` emitted
- [ ] Lint/format clean
- [ ] Live smoke on staging: `make import-n8n ENV=staging` → workflow active; delete + re-import = identical
- [ ] `verification.md` filled with evidence
- [ ] PR referencing this spec; update `infra/n8n/workflows/README.md` (remove the manual UI-import section)
