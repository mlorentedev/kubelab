---
tags: [spec, tasks]
created: "2026-06-14"
---

# Tasks - NOTIFY-001

> TDD order. One task = one focused commit. Staging-first; promote to prod only after the proof.

## Setup

- [x] Branch created: `feat/notification-routing-fabric`
- [x] De-risking checks resolved (Hermes script-curl; n8n route has no Authelia)
- [x] `proposal.md` reviewed; **resolve the OPEN webhook-authn item (shared secret) before exposing** — resolved by n8n Header Auth (`notify-webhook` credential from SOPS); a missing and a wrong secret both get 403 (`make notify-smoke`, 2026-10-10). ✓ 2026-10-10

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
- [x] **n8n workflow** — authored `infra/n8n/workflows/notify-router.json` ✓ 2026-06-14: Webhook POST
      `/webhook/notify` (native Header Auth credential `notify-webhook`) → Code route → HTTP
      `POST http://apprise:8000/notify/kubelab` → Respond 200. JSON + routing JS validated
      (`node --check` + 4-case smoke). **UI import + credential link + activate = operator handoff.**
- [x] **Routing table** — in-workflow Code map ✓ 2026-06-14: `severity` → `{tag,type}` (page→page/failure,
      log→log/info, notice→log until phase-2 digest #95, unknown→fail-safe log). Full `{domain,severity}`
      multi-domain table deferred to phase 3 (per the source audit; see NOTIFY-005..007).
- [x] ~~**hermes-nan migration**~~ — superseded, not done. hermes-nan was retired (AI-009 `proposal.md`, ADR-068),
      so there is no script to migrate. `backup-fail` has a successor through the fabric: `node_backup`'s
      `OnFailure=kubelab-notify@%n.service` → prod `/webhook/notify` (ANSIBLE-035). `watchdog-down` has none:
      kubelab#2175 (AI-013). ✓ 2026-10-10
- [x] **Smoke** — backup-fail: rpi4's `node-backup-capture` timeout on 2026-10-07 reached Slack through the
      fleet path (`verification.md`, criterion #3). watchdog-down: no successor, kubelab#2175. Channel moved
      from Telegram to Slack (ADR-044, NOTIFY-002 addendum). ✓ 2026-10-10

## Checkpoint — 2026-06-14 (mid criterion #2, UNCOMMITTED, NOT deployed)

> Historical. Superseded by the closure on 2026-10-10; kept as the record of how the work ran.

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

## Checkpoint 2 — 2026-06-14 (committed + rebased + workflow authored)

> Historical. Superseded by the closure on 2026-10-10; kept as the record of how the work ran.

> Resume here. The WIP from Checkpoint 1 is now **committed** and the branch is **rebased
> onto master** (was 12 behind, now 0). The n8n workflow is authored + validated in the repo.
> Everything remaining is **operator-gated** (Telegram channels, n8n UI, staging deploy).

**Done this session (all committed on `feat/notification-routing-fabric`):**
- Committed Checkpoint-1 WIP (Apprise Option B: `simple` mode + SOPS-rendered `kubelab.yml`).
- Rebased onto `origin/master` (only conflict was `docs/lessons.md`, resolved keeping both).
- Added `tests/test_k8s_secrets_apprise.py` (3 tests, green) — sibling test for `_build_apprise_config`.
- Verified `kubectl kustomize` base + staging render clean with the apprise objects.
- Authored `infra/n8n/workflows/notify-router.json` + `README.md` (import guide).
- Audited all notification sources (service catalog) → filed the full roadmap on the board:
  epic #90 refreshed; children NOTIFY-002..008 (#95–#101) + APP-CONFIG-003 (#102).

**Operator-gated next steps (cannot be done from the worktree):**
1. SOPS (staging): create a LOG Telegram channel (`kubelab_bot` admin) → set
   `apps.services.automation.apprise.telegram.chat_log`; generate + set
   `apps.services.automation.notify.webhook_secret`. Both via `toolkit secrets set … --env staging`.
2. Deploy staging: `make apply-secrets ENV=staging` (re-renders `apprise-secrets/kubelab.yml`) +
   `make deploy-k8s ENV=staging`; `kubectl rollout restart deploy/apprise -n kubelab` (spoke).
3. n8n UI (staging): create the `notify-webhook` Header Auth credential (paste the SOPS value),
   import `notify-router.json`, link the credential, activate. (See `infra/n8n/workflows/README.md`.)
4. hermes-nan migration (vault `00_meta/agents/scripts/`): point `watchdog`/`backup-fail` at the
   webhook (`curl` the envelope), set their cron `--deliver local`, deploy via the apply loop.
5. Smoke (criteria #2–#4): `page`→PAGE channel, `log`→LOG channel, bad/missing secret→403.
   Force watchdog-down + backup-fail → confirm each lands in its channel. Fill `verification.md`.
6. Open the kubelab PR; commit the hermes change to the vault; tick NOTIFY-001 on the board.

## Closing

- [x] All acceptance criteria green on staging — #1, #2, #4 measured 2026-10-10; #3 dispositioned (half met by the fleet path, half kubelab#2175). ✓ 2026-10-10
- [x] `verification.md` filled with evidence (smoke output, operator confirmation in Slack) ✓ 2026-10-10
- [x] Defer-list held: no NOTICE digest, no prod promotion, no other sources crept in. (Prod promotion and the Slack egress came later, under NOTIFY-002 and their own changes.) ✓ 2026-10-10
- [x] PR opened (kubelab); no hermes change, hermes-nan is retired; knowledge#90 is closed ✓ 2026-10-10
