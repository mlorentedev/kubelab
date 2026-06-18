---
tags: [spec, verification]
---

# Verification - TOOL-009-n8n-workflow-import

> Implementation complete on `feat/notification-routing-fabric`. Unit + dry-run
> evidence below; the live staging smoke is the only remaining gate (needs the
> homelab cluster up).

## Evidence

- [x] Criterion: credential-render unit test → `TestRenderCredential` (5 tests):
      value is `Bearer <secret>`, id/type/name carried, output is a JSON array,
      bare secret rejected, idempotent. All green.
- [x] Criterion: secret never on persistent disk/argv → `test_secret_only_in_stdin_never_in_argv`
      asserts the secret is absent from every argv and present only in stdin;
      `test_credential_lands_in_dev_shm` asserts the tmpfs path. Code review:
      `_exec_stdin_import` passes the payload via `subprocess.run(input=...)`, the
      `sh -c` script `cat`s stdin into `mktemp /dev/shm/...` and shreds on EXIT.
- [x] Criterion: command assembly → `test_three_execs_credential_workflow_activate`
      (import:credentials → import:workflow → update:workflow --active=true, all via
      `kubectl exec` into `deploy/n8n`), `test_activate_uses_workflow_id_from_json`.
- [x] Criterion: missing secret → hard failure → `test_missing_secret_returns_false_and_no_exec`
      (False, kubectl never invoked). Out-of-scope env + dry-run also no-op.
- [x] Dry-run against real SOPS (staging): reads `webhook_secret`, extracts both ids
      from the workflow JSON (`c1…01` credential, `d1…01` workflow), prints the plan,
      cluster untouched.
- [x] Criterion: `make import-n8n ENV=staging` → import:credentials + import:workflow +
      publish:workflow + `kubectl rollout restart` all green; n8n rolled out fresh (new
      pod, age 66s). 2026-06-15.
- [x] Criterion: idempotent re-run → second run upserts by the fixed id ("Successfully
      imported 1 workflow", no duplicate). 2026-06-15.
- [~] Criterion: delete + re-import identical → covered by the fixed-id upsert
      (insert-by-id restores identically; same code path). Explicit delete not exercised
      (no `n8n delete` CLI).

## Test status

- Unit tests: `poetry run pytest tests/test_n8n_import.py` → **18 passed**
- No regressions: `make test` → **222 passed, 108 deselected** (n8n_import.py 84% cov;
  uncovered lines are the subprocess-failure branches, not exercised by success mocks)
- Lint/format/types: `ruff check` + `ruff format` + `mypy toolkit/features/n8n_import.py` → clean
- Live smoke (staging): `make import-n8n ENV=staging` → **green** (import + publish +
  restart; n8n + apprise both Running on ace1). End-to-end POST→Telegram is the
  NOTIFY-001 page/log smoke (next step, not a TOOL-009 criterion).

## Decisions made during implementation

- **Header value = `Bearer <secret>` (RFC 6750), not the raw secret.** Resolved a
  contradiction between the workflow README (showed raw) and the SECRET_CATALOG
  format_hint (Bearer). Confirmed with the user; n8n's own header-auth docs use
  `Authorization: Bearer {{token}}`. README corrected to match; catalog already
  said Bearer.
- **Two stable ids fixed in the workflow JSON, not one.** The spec called out the
  credential id; idempotency also requires a root workflow `id` — `import:workflow`
  upserts by id (no id → a new workflow every run → duplicates). Added
  `id: d1000000-…01` (workflow) alongside `httpHeaderAuth.id: c1000000-…01`
  (credential). Both read from the JSON → single source of truth.
- **Credential file built with `json.dumps`, not a textual `.tpl`.** Departs from the
  tasks.md sub-task: a secret containing quotes/backslashes would break textual
  substitution inside JSON, while `json.dumps` escapes correctly. No `.tpl` file.
- **Activation = `publish:workflow --id` + a rollout restart** (revised after the live
  smoke). The smoke revealed two things: (1) `update:workflow --active` is deprecated and
  n8n points to `publish:workflow --id` (now used); (2) `import:workflow` deactivates the
  workflow and CLI changes only take effect after a restart — the running process caches
  the webhook registry (same gotcha as Gitea OIDC, CLAUDE.md). The orchestrator therefore
  publishes, then `kubectl rollout restart`s n8n and waits for readiness. Without the
  restart the `/webhook/notify` route stays dead despite a "successful" import.
- **`import-n8n` runs as the last step of `make deploy-k8s`, not a prerequisite.** It
  `kubectl exec`s into the n8n pod, which must already be rolled out. Staging-only
  today; a no-op (returns True) on other envs.

## Promotion candidates

- [ ] Lesson for `docs/lessons.md`? yes — "n8n config as code: import workflow +
      Header Auth credential from Git+SOPS via /dev/shm, idempotent by fixed ids"
- [ ] ADR-worthy? no — folds into ADR-044 / APP-CONFIG-003 (the export half)
- [ ] Pattern for `00_meta/patterns/`? maybe — "service config as code via CLI import
      from SOPS" generalizes the ADR-035 injection pattern beyond Traefik middlewares

## Archive checklist

- [x] README manual-import section removed (replaced with `make import-n8n` + contract)
- [x] Live staging smoke green (import + publish + restart, idempotent) 2026-06-15
- [ ] `proposal.md` → `status: archived`
- [ ] Folder → `specs/archive/TOOL-009-n8n-workflow-import/`
- [ ] Issue #108 ticked with PR link
