# n8n workflows (as code)

> Interim manual export/import until **APP-CONFIG-003** (`mlorentedev/knowledge#102`)
> automates `n8n export -> Git`. n8n stores workflows in its SQLite DB (ADR-026 gap),
> so this directory is the versioned source of truth — re-export after any UI edit.

## `notify-router.json` — NOTIFY-001 routing brain (ADR-044)

`POST /webhook/notify` -> route by `severity` -> `POST http://apprise:8000/notify/kubelab`
-> respond `200`. Apprise (stateful `simple` mode) resolves the `tag` to a Telegram
channel via the SOPS-rendered `kubelab.yml` routing table.

- **Envelope** (request body): `{ domain, severity, title, body, source }`.
- **Severity tiers (MVP)**: `page` -> tag `page` (push, type `failure`); `log` -> tag `log`
  (archive, type `info`). `notice` folds to `log` until the phase-2 digest (NOTIFY-002 #95).
  Unknown/missing severity fails **safe** to `log`. `domain` is carried but does not route
  yet (single channel set; multi-domain routing is phase 3).

### One-time import (n8n UI, staging)

1. **Create the credential first.** Credentials -> New -> **Header Auth**, name it
   exactly `notify-webhook`. Header name `Authorization`, value = the SOPS secret
   `apps.services.automation.notify.webhook_secret` (staging). This is criterion #4:
   n8n rejects any POST with a missing/wrong header automatically (HTTP 403).
2. **Import** `notify-router.json` (Workflows -> Import from File).
3. On the **Webhook notify** node, confirm the credential resolves to `notify-webhook`
   (the exported JSON references it by name; re-select if the UI shows it unlinked).
4. **Activate** the workflow. Production URL: `https://n8n.staging.kubelab.live/webhook/notify`.

### Sources call it like

```
POST https://n8n.staging.kubelab.live/webhook/notify
Authorization: <webhook_secret>
Content-Type: application/json

{ "domain": "ops", "severity": "page", "title": "watchdog down",
  "body": "hermes-nan unreachable", "source": "hermes-nan/watchdog" }
```

### After editing in the UI

Re-export (Workflows -> ... -> Download) and overwrite `notify-router.json` so Git stays
the source of truth, until APP-CONFIG-003 automates the round-trip.
