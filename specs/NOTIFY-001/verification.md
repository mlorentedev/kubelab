---
tags: [spec, verification]
created: "2026-06-14"
---

# Verification — NOTIFY-001

> Status: **Fabric proven end to end on staging (criteria #1, #2, #4 green).** `POST
> /webhook/notify` routes `page`/`log` to Telegram and rejects unauthenticated POSTs with 403,
> reproducible via `make notify-smoke ENV=staging`. Criterion #3 (hermes-nan migration off the
> legacy `deliver: telegram:`) remains open — it's a vault-side agent-script change, not a
> kubelab artifact.

## Environment

- Cluster: staging spoke `ace1` (k3s v1.34.4+k3s1), namespace `kubelab`, via Tailscale
  (`~/.kube/kubelab-staging-config` → `https://100.64.0.11:6443`).
- Deploy mechanism: direct `kubectl apply` of the Apprise objects. Staging is a mutable test bed
  (ADR-037; the ArgoCD `kubelab-staging` app runs `selfHeal: false`), so a feature-branch service is
  applied directly rather than merged to `master` first. ArgoCD will show the resource OutOfSync
  until the branch merges — expected, harmless.

## Acceptance criteria

- [x] **#1 — Apprise live in staging; in-cluster `curl /notify` delivers to Telegram.**
- [x] **#2 — `POST /webhook/notify` routes `page`/`log` to Telegram.** notify-smoke: page→200, log→200;
  operator confirmed both landed (PAGE + LOG channels). `{domain}` carried but single-channel today.
- [ ] #3 — hermes-nan `watchdog-down` routes through n8n, not the legacy `deliver: telegram:`. *(open —
  vault-side agent-script change.)*
- [x] **#4 — a POST with a missing shared secret is rejected (HTTP 403).** notify-smoke unauthenticated probe.

## Evidence — criterion #1

**Manifest / pin.** `infra/k8s/base/services/apprise.yaml` — stateless `caronc/apprise:1.5.0`
(ConfigMap + Deployment + Service, ClusterIP, **no IngressRoute**, `APPRISE_STATEFUL_MODE=disabled`).
Image pinned through the SSOT (`common.yaml` + `sync_k8s_images.IMAGE_SOURCES`). `kubectl kustomize`
renders clean on base (4321 lines) and the staging overlay (4643 lines).

**Rollout — OOM caught & fixed.** First rollout CrashLooped: `OOMKilled` (exit 137) under the 256Mi
limit. Root cause: the image defaults `APPRISE_WORKER_COUNT` to `(2*CPUS)+1`, ~9–17 gunicorn workers
on a multi-core node. Fix (declarative, no live-pod patching): `APPRISE_WORKER_COUNT=2` + 384Mi limit.
Fresh pod reached Ready in ~20s. Captured in `docs/lessons.md` (2026-06-14).

**Credentials (toolkit-wired).** `apprise-secrets` Secret rendered from SOPS:
`apps.services.automation.apprise.telegram.bot_token` (→`common.enc.yaml`, shared bot = `kubelab_bot`)
and `.chat_page` (→`staging.enc.yaml`, dedicated PAGE channel). Registered in `SECRET_CATALOG`
(`secrets_manager.py`) and `SECRET_DEFINITIONS` (`k8s_secrets.py`). Verified the live Secret carries
keys `TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_PAGE` (values not printed).

**Channel separation (ADR-044 C5).** Deliveries go to a dedicated private Telegram channel
(`kubelab · page · staging`, `kubelab_bot` as admin), distinct from the chat hermes uses — so staging
test traffic does not pollute the live ops stream and the eventual hermes→fabric migration stays
observable.

**Smoke (in-cluster, secret never logged).** From a throwaway `curlimages/curl` pod with
`envFrom: apprise-secrets`, building `tgram://$TELEGRAM_BOT_TOKEN/$TELEGRAM_CHAT_PAGE` inside the pod:

- `GET http://apprise:8000/status` → `OK`, **HTTP 200** (Service DNS resolves; the n8n→apprise path).
- `POST http://apprise:8000/notify/` (stateless, `urls=tgram://…`) → apprise log
  `Sent Telegram notification.`, **HTTP 200**; message confirmed in the dedicated channel by the operator.

## Evidence — criteria #2 & #4 (2026-06-16)

**Apprise `/status` 417 → fixed.** With Option B live (`simple` mode + the SOPS config mounted read-only
at `/config`), apprise CrashLooped: `/status` returned 417 (config dir not writable — see
`docs/lessons.md` 2026-06-16) and the liveness probe killed the pod (0/1, 14 restarts). Fix
(`infra/k8s/base/services/apprise.yaml`): `/config` is now a writable `emptyDir` seeded with
`kubelab.yml` by an initContainer (reusing `caronc/apprise:1.5.0`). Verified on staging: pod **1/1**,
`/status` **200**, and `POST /notify/kubelab` with `tag=page`/`tag=log` → apprise `Sent Telegram
notification.` for each.

**End-to-end via the real webhook — `make notify-smoke ENV=staging`.** New toolkit command
(`toolkit infra n8n smoke`, `toolkit/features/notify_smoke.py`, 9 unit tests) POSTs page + log envelopes
to `https://n8n.staging.kubelab.live/webhook/notify` with the Bearer secret from SOPS:

```
page (authenticated):   HTTP 200 (expected 200) -> ok
log  (authenticated):   HTTP 200 (expected 200) -> ok
unauthenticated reject: HTTP 403 (expected 403) -> ok
```

Operator confirmed the page + log messages landed in their Telegram channels. This closes #2 (routing)
and #4 (auth) at the HTTP level; Telegram read-back stays manual (no synthetic probe yet).

## Notes / follow-ups

- Deferred to the n8n-workflow stage: the routing decision **Option A (n8n holds URLs, stateless Apprise)
  vs Option B (Apprise tag→URL config from SOPS)** — ADR-044 points to B. The MVP manifest is
  compatible with both; B adds a mounted config + `chat_log`/`chat_notice` tiers.
- The webhook shared-secret/HMAC (criterion #4) gates exposing the endpoint to real sources.
- `toolkit` coupling (per-service hardcoded `SECRET_CATALOG`/`DEFINITIONS`/`IMAGE_SOURCES`) noted as a
  future refactor candidate — derive registries from `common.yaml` SSOT.
