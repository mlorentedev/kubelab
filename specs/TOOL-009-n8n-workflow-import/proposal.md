---
id: "TOOL-009-n8n-workflow-import"
type: spec
status: draft # draft | implementing | verifying | archived
issue: "mlorentedev/knowledge#108"  # created via REST (gh api) — gh issue create uses GraphQL, which was rate-limited
tags: [spec, proposal, toolkit, n8n, notifications, gitops]
template_version: "1.0"
---

# TOOL-009-n8n-workflow-import

> Surfaced by NOTIFY-001. Consistent with TOOL-008: toolkit capability surfaced by NOTIFY-001 → its own spec.

## Why

NOTIFY-001 versions the n8n workflow (`infra/n8n/workflows/notify-router.json`) in git, but importing
it into n8n is a **manual UI step** today — not versionable, not reproducible, and lost on a PVC wipe
(n8n stores workflows + credentials in encrypted SQLite). A fresh cluster, or a wiped `n8n-data` PVC,
must rebuild the n8n workflow **and** its Header Auth credential from git + SOPS without touching the
UI. Durability must come from source (git structure + SOPS secret + `N8N_ENCRYPTION_KEY`), not from a
mutable PVC — "cattle, not pets" applied to n8n.

## What

Observable behavior after this PR:

- **`toolkit infra n8n import --env <e>`** (new `n8n` subgroup under `infra`, parallel to `argo` /
  `headscale`) and **`make import-n8n ENV=<e>`**, wired into `make deploy-k8s` so a deploy
  reconstructs the workflow automatically.
- The command:
  1. reads `apps.services.automation.notify.webhook_secret` from SOPS (decrypt in memory);
  2. renders the `notify-webhook` Header Auth credential JSON with a **fixed id** (sourced from the
     workflow JSON, see below);
  3. pipes it into the n8n pod via `/dev/shm` (tmpfs — never persistent disk), imports it with
     `n8n import:credentials`, and shreds the temp file;
  4. imports `notify-router.json` with `n8n import:workflow`;
  5. activates with `n8n update:workflow --id <id> --active=true` (no API key needed).
- Idempotent: fixed credential id → re-import is an upsert (no duplicates). Mirrors the ADR-035
  middleware-secret injection pattern (SOPS → render → inject, plaintext never persisted).

### Single source of the credential id

The workflow JSON references its credential by id (today `"REPLACE_ON_IMPORT"`). We fix it to a stable
UUID **in the workflow JSON**, and the toolkit **reads that id** and stamps the same id on the imported
credential. One source of truth for the id → no "credential id X but workflow points at Y → node
disconnected" drift.

## Out of scope

- n8n → Git **export** (the reverse half: APP-CONFIG-003).
- Generic multi-workflow import — MVP imports `notify-router`; the design allows extension (iterate a
  manifest of workflows) without rework.
- Interactive UI / web flows.

## Risks / open questions

- **[verify in impl]** Exact JSON shape n8n 2.12 expects for `import:credentials` of an `httpHeaderAuth`
  credential (the decrypted `data` block: `{name, type, data:{name,value}}`), and that import re-encrypts
  with `N8N_ENCRYPTION_KEY`. Confirm via n8n docs/CLI before locking the template.
- **[resolved]** Activation without an API key → `n8n update:workflow --id <id> --active=true`.
- **[resolved]** Secret never on persistent disk → piped to `/dev/shm` (RAM tmpfs) inside the pod,
  removed immediately; never on argv.
- **[dependency]** Implementation rides the notify branch (needs the `webhook_secret` catalog entry)
  and lands after TOOL-008 (#104) merges + notify rebases.

## Acceptance criteria

- [ ] `make import-n8n ENV=staging` imports credential + workflow and leaves it **active**, no UI.
- [ ] Re-running is idempotent (fixed id = upsert; no duplicate workflow/credential).
- [ ] `webhook_secret` never lands on persistent disk or in argv (only `/dev/shm`, then removed).
- [ ] Deleting the workflow in n8n and re-running `make import-n8n` restores it identically.
- [ ] Sibling unit test covers the credential render (id sourced from the workflow JSON) + command
      assembly (no live cluster needed).

## References

- Surfaced by: NOTIFY-001 (`specs/NOTIFY-001/`, mlorentedev/knowledge#90)
- Pattern precedent: ADR-035 middleware-secret injection (`toolkit/features/k8s_middlewares.py`,
  `apply_middleware_secrets`)
- CLI placement precedent: `toolkit infra argo`, `toolkit infra headscale`
- Related: APP-CONFIG-003 (n8n export→Git, the complementary half)
- Depends on: TOOL-008 (#104) + `webhook_secret` in `SECRET_CATALOG`
