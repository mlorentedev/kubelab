---
tags: [spec, tasks]
---

# Tasks - TOOL-009-n8n-workflow-import

> **RECONCILED 2026-06-23** — implementation shipped & verified earlier (see `verification.md`: 18 unit tests, live staging smoke green + idempotent 2026-06-15); `toolkit/features/n8n_import.py` in master; issue `knowledge#108` CLOSED. Spec archived retroactively. The two unticked Closing boxes (`features.json`, PR) reflect the board-reconciliation gap, not missing work.
>
> TDD order. Implementation rides the notify branch after TOOL-008 (#104) merges + notify rebases
> (needs the `webhook_secret` catalog entry).

## Setup

- [x] Issue gate: mlorentedev/knowledge#108 (created via `gh api` REST — `gh issue create` uses GraphQL, which was rate-limited)
- [x] `proposal.md` complete; acceptance criteria testable
- [ ] Add #108 to the Bitácora Project board (deferred — needs GraphQL; verify whether auto-add already did it)
- [x] Confirm n8n `import:credentials` JSON shape for `httpHeaderAuth` ✓ 2026-06-15 (n8n docs via context7: import/export use a JSON array of `{id,name,type,data}`; `--input=FILE` consumes the export shape)

## Implementation

- [x] Fix credential id in `notify-router.json` (`REPLACE_ON_IMPORT` → `c1…01`) + add root workflow `id` `d1…01` ✓ 2026-06-15 (both ids needed for idempotent upsert)
- [x] Failing test: credential JSON render reads `webhook_secret` from SOPS + id from the workflow JSON ✓ 2026-06-15
- [x] Failing test: command assembly (import:credentials via `/dev/shm`, import:workflow, update:workflow --active) ✓ 2026-06-15
- [x] Failing test: missing `webhook_secret` → clear error, no partial import ✓ 2026-06-15
- [x] Implement `toolkit/features/n8n_import.py` (render + exec assembly + idempotency) ✓ 2026-06-15
- [x] Wire CLI: new `n8n` subgroup under `infra` → `toolkit infra n8n import --env <e>` ✓ 2026-06-15
- [~] ~~Add `infra/n8n/workflows/credentials/notify-webhook.json.tpl`~~ — N/A: credential built with `json.dumps` (robust secret escaping), no textual template. See verification.md.
- [x] Makefile: `import-n8n` target + hook into `deploy-k8s` (last step — needs the pod up) ✓ 2026-06-15
- [~] Refactor: reuse a SOPS-render helper from `k8s_middlewares` — N/A: middleware render is textual YAML substitution; credential render is `json.dumps`. SOPS read (`get_secret_by_path`) is already shared via `ConfigurationManager`.

## Closing

- [x] Acceptance criteria covered by tests; `make test` green ✓ 2026-06-15 (222 passed; idempotency/delete+re-import criteria gated on the live smoke below)
- [ ] `features.json` emitted
- [x] Lint/format clean ✓ 2026-06-15 (ruff + mypy)
- [ ] Live smoke on staging: `make import-n8n ENV=staging` → workflow active; delete + re-import = identical
- [x] `verification.md` filled with evidence ✓ 2026-06-15
- [ ] PR referencing this spec
- [x] Update `infra/n8n/workflows/README.md` (manual UI-import section removed) ✓ 2026-06-15
