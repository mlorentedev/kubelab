---
tags: [spec, tasks]
created: "2026-06-14"
---

# Tasks - NOTIFY-001

> TDD order. One task = one focused commit. Staging-first; promote to prod only after the proof.

## Setup

- [x] Branch created: `feat/notification-routing-fabric`
- [x] De-risking checks resolved (Hermes script-curl; n8n route has no Authelia)
- [ ] `proposal.md` reviewed; **resolve the OPEN webhook-authn item (shared secret) before exposing**

## Implementation

- [x] **Apprise manifest** — `infra/k8s/base/services/apprise.yaml` (ConfigMap + Deployment + Service,
      cluster-internal, no IngressRoute) + pin `caronc/apprise:1.5.0` via SSOT (`common.yaml` +
      `IMAGE_SOURCES`) → `kustomization.yaml`. Renders clean on base + staging (`kubectl kustomize`).
- [x] **Apprise creds** — wired `apps.services.automation.apprise.telegram.{bot_token,chat_page}` in SOPS
      (`bot_token`→common, `chat_page`→staging) + `SECRET_CATALOG`/`SECRET_DEFINITIONS` (`apprise-secrets`);
      `apply-secrets --env staging` renders the Secret. Dedicated PAGE channel (kubelab_bot admin), separate
      from the hermes chat (ADR-044 C5).
- [x] **Deploy to staging** → `kubectl apply` of the Apprise objects (staging is a mutable test bed,
      ADR-037; ArgoCD selfHeal=false). Pod Ready after fixing an OOMKill (capped `APPRISE_WORKER_COUNT=2`).
      Verified: in-cluster `curl apprise:8000/status`→200; `POST /notify/` with `tgram://`→Telegram (HTTP 200,
      message landed in the dedicated channel).
- [ ] **n8n workflow** — webhook `/webhook/notify` → validate shared secret → Switch `{domain,severity}`
      → HTTP Request to Apprise; **export workflow JSON into the repo** (APP-CONFIG-003 interim: manual export)
- [ ] **Routing table** — encode `{domain,severity}` → Apprise tag(s) (ConfigMap or in-workflow map)
- [ ] **hermes-nan migration** — edit `watchdog`/`backup-fail` scripts (vault `00_meta/agents/scripts/`)
      to `curl` the envelope; set their cron `--deliver local`; deploy via the apply loop (NOT by hand)
- [ ] **Smoke** — force watchdog-down + backup-fail → confirm each lands in the right Telegram channel

## Checkpoint — 2026-06-14 (mid criterion #2, UNCOMMITTED, NOT deployed)

> Resume here. IaC for Option B is scaffolded but not committed/applied; the n8n workflow
> and the SOPS values are not done yet. Nothing is half-written — render is clean
> (`kubectl kustomize infra/k8s/base` → exit 0).

**Done this session (3 modified files, uncommitted):**
- `infra/k8s/base/services/apprise.yaml` — `APPRISE_STATEFUL_MODE: disabled→simple`; mount
  `apprise-secrets` (key `kubelab.yml`) read-only at `/config` → `POST /notify/kubelab` resolves tags.
- `toolkit/features/k8s_secrets.py` — `apprise-secrets` repurposed to a file Secret; new
  `_build_apprise_config()` renders `kubelab.yml` (tag `page`→chat_page, `log`→chat_log) from SOPS,
  registered in `_build_dynamic_literals`.
- `toolkit/features/secrets_manager.py` — catalog: added `apprise.telegram.chat_log` and
  `apps.services.automation.notify.webhook_secret` (RANDOM_TOKEN, n8n Header Auth, mirrored in SOPS).

**Decisions locked:** Option B mechanics = `simple` mode + mounted `/config/kubelab.yml` (caronc/apprise:
`/notify/{KEY}` only resolves tags in stateful mode). Webhook auth = **n8n native Header Auth credential**
(`notify-webhook`), NOT `$env` (n8n v2 defaults `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`; chosen to avoid a
cluster-wide security regression). Routing node = a **Code node** (severity→{tag,type}) — robust to
hand-author + import, no `$env` needed; real multi-branch Switch arrives with phase-2 NOTICE/Redis.

**Next steps (in order):**
1. SOPS: `toolkit secrets set apps.services.automation.apprise.telegram.chat_log "<LOG channel ID>" --env staging`
   (needs a LOG Telegram channel with `kubelab_bot` admin) + generate the webhook secret
   (`toolkit secrets set apps.services.automation.notify.webhook_secret "<token>" --env staging`).
2. Author `infra/n8n/workflows/notify-router.json` (Webhook POST `/webhook/notify`, Header Auth →
   Code route → HTTP `POST http://apprise:8000/notify/kubelab` `{tag,title,body,type}` → Respond 200).
3. Deploy staging: `toolkit secrets apply --env staging` (renders apprise-secrets/kubelab.yml) +
   `kubectl --kubeconfig ~/.kube/kubelab-staging-config apply` the apprise objects; restart pod.
4. n8n UI: import workflow, create the `notify-webhook` Header Auth credential (paste SOPS value),
   activate. Smoke: `page`→PAGE channel, `log`→LOG channel, bad/missing secret→rejected. Fill verification.md.
5. Before PR: rebase branch on `origin/master` (1 behind = the ADR-044 merge).

## Closing

- [ ] All acceptance criteria green on staging
- [ ] `verification.md` filled with evidence (curl output, n8n execution logs, Telegram screenshots)
- [ ] Defer-list held: no NOTICE digest, no prod promotion, no other sources crept in
- [ ] PR opened (kubelab) + hermes change committed to vault; NOTIFY-001 ticked on the bitácora board
