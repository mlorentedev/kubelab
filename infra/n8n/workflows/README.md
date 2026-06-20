# n8n workflows (as code)

> **Import** is automated by **TOOL-009** (`make import-n8n ENV=staging`). **Export**
> (n8n -> Git) is still manual until **APP-CONFIG-003** (`mlorentedev/knowledge#102`).
> n8n stores workflows in its SQLite DB (ADR-026 gap), so this directory is the
> versioned source of truth — re-export after any UI edit.

## `notify-router.json` — NOTIFY-001 routing brain (ADR-044)

`POST /webhook/notify` -> route by `severity` -> `POST http://apprise:8000/notify/kubelab`
-> respond `200`. Apprise (stateful `simple` mode) resolves the `tag` to a Telegram
channel via the SOPS-rendered `kubelab.yml` routing table.

- **Envelope** (request body): `{ domain, severity, title, body, source }`.
- **Severity tiers (MVP)**: `page` -> tag `page` (push, type `failure`); `log` -> tag `log`
  (archive, type `info`). `notice` folds to `log` until the phase-2 digest (NOTIFY-002 #95).
  Unknown/missing severity fails **safe** to `log`. `domain` is carried but does not route
  yet (single channel set; multi-domain routing is phase 3).

### Import (automated — TOOL-009)

```bash
make import-n8n ENV=staging
```

Reconstructs the **credential** and the **workflow** from Git + SOPS with no UI steps,
then activates it. Runs automatically as the last step of `make deploy-k8s`.

- The **Header Auth** credential `notify-webhook` is rendered from the SOPS secret
  `apps.services.automation.notify.webhook_secret`: header name `Authorization`, value
  `Bearer <secret>` (RFC 6750). This is criterion #4 — n8n rejects any POST with a
  missing/wrong header automatically (HTTP 403).
- Both ids are fixed in `notify-router.json` (workflow root `id` + the node's
  `httpHeaderAuth.id`), so re-running is an idempotent upsert (no duplicates). Delete
  the workflow in n8n and re-run to restore it identically.
- The secret reaches the pod via `/dev/shm` (tmpfs) only — never persistent disk, never
  argv. Mirrors the ADR-035 middleware-secret injection pattern.

Production URL after activation: `https://n8n.staging.kubelab.live/webhook/notify`.

### Sources call it like

```
POST https://n8n.staging.kubelab.live/webhook/notify
Authorization: Bearer <webhook_secret>
Content-Type: application/json

{ "domain": "ops", "severity": "page", "title": "watchdog down",
  "body": "hermes-nan unreachable", "source": "hermes-nan/watchdog" }
```

### After editing in the UI

Re-export (Workflows -> ... -> Download) and overwrite `notify-router.json` so Git stays
the source of truth, until APP-CONFIG-003 automates the round-trip.
