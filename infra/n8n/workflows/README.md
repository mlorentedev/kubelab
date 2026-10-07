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
  the notification or the 201. The 201 carries the new task's `id` — the cheapest
  observable that a task exists (#1659). The notice names only what happened (a task
  was created) and deliberately does not name a bucket — `targetBucket` is computed
  and never written to Vikunja (#1687).

### Two n8n behaviours the code nodes depend on

Both are properties of n8n's item model rather than choices this workflow makes, and
both are pinned by tests, because getting either wrong fails in a way that reads as
something else entirely:

- **An HTTP node handed a JSON array emits one item per element.** So `$json` in the
  following Code node is the *first* task or project, not the list. Every code node
  here reads `$input.all()` and normalises the shape; reading `$json` would make the
  search find nothing while looking straight at the results — creating a duplicate —
  and make project resolution answer 422 for every repository.
- **A node that yields no data emits no item, and a node with no input does not run.**
  `GET /tasks?s=<a brand-new key>` returning `[]` is the primary case the create path
  exists for, so both GET nodes set `alwaysOutputData`. Without it the chain stops
  dead, no respond node fires, and the webhook times out.

The same reasoning applies after the create request: `$json` there is Vikunja's new
task object, so both post-create nodes reach back with `$('Pick Project for Repo')`
for the event and take only `id` from `$json`.

Trigger floor: `opened` and `reopened`, which is exactly what the
`add-to-project.yml` this replaces fired on. `closed`/`edited` answer 200 without
creating. An issue whose title carries no `AREA-NNN` key reaches no board.

---

## `sre-auto-triage.json` — SRE Auto-Triage & Self-Healing Brain (ADR-064)

`POST /webhook/sre-triage` -> parse alert labels & annotations -> query Loki telemetry -> 4-step root cause classifier -> `POST http://apprise:8000/notify/kubelab` (tag `agent`) -> respond `200 JSON`.

- **Envelope**: Alertmanager alert object or `{ service, alert_name, severity, query, thread_ts }`.
- **Diagnostic Engine**: Fingerprints tracebacks, correlates with SRE runbooks, and classifies OOMKilled, Connection Refused, and Timeout signatures.
- **Import**: `make import-n8n ENV=staging` (idempotent upsert).

---

## Sending email from a workflow — `kubelab-smtp`

Email goes through one shared n8n **SMTP** credential, `kubelab-smtp`, declared in
`N8N_SHARED_CREDENTIALS` (`toolkit/features/n8n_import.py`) and rendered at import from the
relay the API and Authelia already use (`infra.smtp.host`, `.port`, `.user`, `.pass`; ADR-036).
It belongs to no workflow: it is imported once per run however many reference it, and removing a
workflow never removes it. Today it is imported in **prod** only; widen `envs` on the registry
entry when a staging workflow needs it.

To send an email from a new workflow:

1. Put an **Email Send** node in the JSON and reference the credential by id and name, nothing else:

   ```json
   "credentials": { "smtp": { "id": "c9000000-0000-4000-8000-000000000001", "name": "kubelab-smtp" } }
   ```

2. Set `fromEmail` to the token `RESOLVE_KUBELAB_SMTP_FROM`. It resolves to `infra.smtp.user`, the
   relay's own account. That is the **default sender convention**, and the only one the relay allows:
   Gmail rewrites any other From to the authenticated account.
3. Add the catalog entry. A workflow whose only credential is this one needs just its path and envs:
   `N8nImportSpec(workflow_path=Path("infra/n8n/workflows/<name>.json"), envs=frozenset({"prod"}))`.
4. `make import-n8n ENV=prod`. The import refuses the workflow if a node references a credential
   nothing in the run imports, or references `kubelab-smtp` under another id.

`secure` on the credential is derived from the port, not copied from `infra.smtp.secure`: n8n's
flag means implicit TLS (port 465), and port 587 is STARTTLS (`secure: false`) although
`infra.smtp.secure` is `true` for the API.

---

## `sale-metrics-daily-digest.json` — leaving-denver sale digest (APP-CONFIG-018)

"Moving Sale - Daily Metrics Digest" (leaving-denver#225, its ADR-011): every day at 08:00
America/Denver it reads the sale's first-party events (Workers Analytics Engine) and Cloudflare
Web Analytics for the last 24 hours and the whole sale, and emails one Spanish digest (HTML with a
plain-text fallback: subject, three headline tiles, the most-viewed items, where visitors come from, and
the repricing candidates). A failed query is named in the email rather than stopping it. **Prod only.**
Like every workflow here it is **live as soon as it is imported** (`publish:workflow`): the first
email is the next 08:00 Denver, or run it once from the n8n UI.

It carries nothing in the repository that is not public, and reads nothing from `$env` (n8n 2
blocks it, and a changed value would go stale silently). Everything is filled at import:

| What | Where it comes from |
|---|---|
| Header Auth credential `cloudflare-analytics-read` (`Authorization: Bearer <token>`) | SOPS `apps.services.automation.n8n.sale_digest.analytics_token`, a Cloudflare token with **Account \| Account Analytics \| Read** |
| Recipient (`RESOLVE_SALE_DIGEST_TO`) | SOPS `apps.services.automation.n8n.sale_digest.recipient` |
| Web Analytics site tag (`RESOLVE_SALE_DIGEST_SITE_TAG`) | SOPS `apps.services.automation.n8n.sale_digest.site_tag` |
| Sender (`RESOLVE_KUBELAB_SMTP_FROM`) and the SMTP credential | `infra.smtp.*`, through the shared `kubelab-smtp` above |

The Cloudflare account id is inline in the JSON: it is an identifier, not a credential. If one of
the three `sale_digest` values is absent the import fails that workflow, before any `kubectl`,
naming the path. The values are never printed.

Set them with `toolkit secrets set <path> --env prod --stdin` (see `docs/runbooks/sops-and-secrets.md`),
then `make import-n8n ENV=prod`. The token is minted in the Cloudflare dashboard (My Profile > API Tokens
> Create Custom Token, permission Account | Account Analytics | Read, this account only, TTL ending
2026-11-15). `toolkit secrets check-expiry` asks Cloudflare when it dies.

### Removing the sale (2026-11-09 and after)

1. Delete the `sale-metrics-daily-digest.json` entry from `N8N_IMPORT_CATALOG` and the file.
2. Delete the three `apps.services.automation.n8n.sale_digest.*` entries from `SECRET_CATALOG`
   (`toolkit/features/secrets_manager.py`), their `PROVIDER_CHECKS` line in
   `toolkit/features/secret_expiry.py`, and the `RESOLVE_SALE_DIGEST_*` lines in `PLACEHOLDER_SSOT`.
   Then remove the SOPS block with `toolkit secrets unset apps.services.automation.n8n.sale_digest --env prod`
   and revoke the Cloudflare token.
3. The import never deletes. In n8n, delete the workflow `Moving Sale - Daily Metrics Digest` (id
   `d5000000-0000-4000-8000-000000000001`) and the Header Auth credential `cloudflare-analytics-read`
   (id `c5000000-0000-4000-8000-000000000001`). Both are reproducible from git, so deleting them is
   safe.
4. **Leave `kubelab-smtp` alone.** It is shared, and it stays in the registry, in n8n and in the
   import. `tests/test_n8n_shared_credentials.py::TestSharedLifecycle` fails if removing the sale
   would take it with it.
