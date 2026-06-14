---
tags: [spec, verification]
created: "2026-06-14"
---

# Verification — NOTIFY-001

> Status: **MVP spine proven on staging (acceptance criterion #1 green).** Criteria #2–4 (n8n
> routing workflow, severity tiers, hermes-nan migration, webhook shared-secret) remain open —
> they belong to the n8n-workflow stage, not yet built.

## Environment

- Cluster: staging spoke `ace1` (k3s v1.34.4+k3s1), namespace `kubelab`, via Tailscale
  (`~/.kube/kubelab-staging-config` → `https://100.64.0.11:6443`).
- Deploy mechanism: direct `kubectl apply` of the Apprise objects. Staging is a mutable test bed
  (ADR-037; the ArgoCD `kubelab-staging` app runs `selfHeal: false`), so a feature-branch service is
  applied directly rather than merged to `master` first. ArgoCD will show the resource OutOfSync
  until the branch merges — expected, harmless.

## Acceptance criteria

- [x] **#1 — Apprise live in staging; in-cluster `curl /notify` delivers to Telegram.**
- [ ] #2 — `POST /webhook/notify` routes `page`/`log` by `{domain,severity}`. *(n8n workflow — open.)*
- [ ] #3 — hermes-nan `watchdog-down` routes through n8n, not the legacy `deliver: telegram:`. *(open.)*
- [ ] #4 — a POST with a wrong/missing shared secret is rejected. *(webhook authn — open.)*

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

## Notes / follow-ups

- Deferred to the n8n-workflow stage: the routing decision **Option A (n8n holds URLs, stateless Apprise)
  vs Option B (Apprise tag→URL config from SOPS)** — ADR-044 points to B. The MVP manifest is
  compatible with both; B adds a mounted config + `chat_log`/`chat_notice` tiers.
- The webhook shared-secret/HMAC (criterion #4) gates exposing the endpoint to real sources.
- `toolkit` coupling (per-service hardcoded `SECRET_CATALOG`/`DEFINITIONS`/`IMAGE_SOURCES`) noted as a
  future refactor candidate — derive registries from `common.yaml` SSOT.
