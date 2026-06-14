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

- [ ] **Apprise manifest** — `infra/k8s/base/services/apprise.yaml` (Deployment + Service,
      cluster-internal, no IngressRoute) + pin `caronc/apprise` in `infra/k8s/base/kustomization.yaml`
- [ ] **Apprise creds** — `toolkit secrets edit --env staging` add `apps.services.automation.apprise.*`
      (bot tokens, chat IDs) → `toolkit infra k8s apply-secrets --env staging`
- [ ] **Deploy to staging** (ArgoCD sync) → verify in-cluster `curl apprise/notify` → Telegram
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
