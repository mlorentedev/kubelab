# n8n workflows (as code)

> **Import** is automated by **TOOL-009** (`make import-n8n ENV=staging`). **Export**
> (n8n -> Git) is still manual until **APP-CONFIG-003** (`mlorentedev/knowledge#102`).
> n8n stores workflows in its SQLite DB (ADR-026 gap), so this directory is the
> versioned source of truth — re-export after any UI edit.

## `notify-router.json` — NOTIFY-001 routing brain (ADR-044)

`POST /webhook/notify` -> route by `severity` -> `POST http://apprise:8000/notify/kubelab`
-> respond `200`. Apprise (stateful `simple` mode) resolves the `tag` to a Slack
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

---

## `multi-forge-sync.json` — forge -> Vikunja (ADR-066 D4)

One webhook (`POST /webhook/multi-forge-sync`), one HMAC check, two paths. The forge
events it is subscribed to are declared in `apps.services.core.gitea.webhook.events`
and written by `make gitea-reconcile`.

`Parse Forge Event` verifies the signature (fail-closed) and extracts the task key
`AREA-NNN` from the title and branch. **That key is the join key of the whole
integration**: the only lookup either path has is `GET /api/v1/tasks?s=<key>`, a
search over titles, so a task whose title does not carry the key is unreachable.
Vikunja has no custom fields — the title is the only place it can live.

| event | path | writes |
|---|---|---|
| `pull_request`, `push` | find the task by key -> update state | `{done}` on merge |
| `issues` (`opened`, `reopened`) | find by key -> **create it if absent** | a new task |

The two are split immediately after the signature gate (`Is Issue Event?`), so an
issue event can never reach `Update Vikunja Task State` and write `done: false` over
a task somebody finished.

### The create path, and what it refuses to do

- **Idempotent** by an EXACT key match, not by "the search returned something":
  `?s=` is a substring search, so `?s=TOOL-035` also matches `TOOL-0350`.
- **A failed search is not an empty search.** `continueOnFail` turns a 401 into an
  item carrying `error`, shaped exactly like "found nothing". Creating on it would
  duplicate a task that exists, so it blocks instead.
- **No default project.** `slack-task-capture` falls back to project `1` because a
  human sees where the task landed; nothing watches a webhook. If no Vikunja project
  matches the repository or its owning organisation, the workflow answers **422** and
  the forge records a failed delivery — a task filed in the wrong project looks
  exactly like one filed correctly.
- **The create request has no `continueOnFail`**, so a create that 401s cannot reach
  the notification or the 201. The notice names only what happened (a task was
  created) and deliberately does not name a bucket — `targetBucket` is computed and
  never written to Vikunja (#1687).

Trigger floor: `opened` and `reopened`, which is exactly what the
`add-to-project.yml` this replaces fired on. `closed`/`edited` answer 200 without
creating. An issue whose title carries no `AREA-NNN` key reaches no board.

---

## `sre-auto-triage.json` — SRE Auto-Triage & Self-Healing Brain (ADR-064)

`POST /webhook/sre-triage` -> parse alert labels & annotations -> query Loki telemetry -> 4-step root cause classifier -> `POST http://apprise:8000/notify/kubelab` (tag `agent`) -> respond `200 JSON`.

- **Envelope**: Alertmanager alert object or `{ service, alert_name, severity, query, thread_ts }`.
- **Diagnostic Engine**: Fingerprints tracebacks, correlates with SRE runbooks, and classifies OOMKilled, Connection Refused, and Timeout signatures.
- **Import**: `make import-n8n ENV=staging` (idempotent upsert).
