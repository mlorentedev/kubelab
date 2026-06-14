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

## Closing

- [ ] All acceptance criteria green on staging
- [ ] `verification.md` filled with evidence (curl output, n8n execution logs, Telegram screenshots)
- [ ] Defer-list held: no NOTICE digest, no prod promotion, no other sources crept in
- [ ] PR opened (kubelab) + hermes change committed to vault; NOTIFY-001 ticked on the bitácora board
