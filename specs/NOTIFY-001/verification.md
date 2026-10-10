---
tags: [spec, verification]
created: "2026-06-14"
---

# Verification — NOTIFY-001

> Status: **closed 2026-10-10.** Criteria #1, #2 and #4 re-measured on staging through the real
> webhook (`make notify-smoke ENV=staging`, four probes), with the delivery confirmed in Slack by the
> operator. The channel is Slack, not the Telegram the proposal names: ADR-044's 2026-08-22 addendum
> (NOTIFY-002) retired the Telegram sink, and `proposal.md` stands unchanged as the record of what was
> planned. Criterion #3's subject, hermes-nan, is retired. Its `backup-fail` half is met by the fleet
> failure path through the fabric, and its `watchdog-down` half has no successor, ticketed as
> kubelab#2175 (AI-013).

## Environment

- Cluster: staging spoke `ace1` (k3s v1.34.4+k3s1), namespace `kubelab`, via Tailscale
  (`~/.kube/kubelab-staging-config` → `https://100.64.0.11:6443`).
- Deploy mechanism: direct `kubectl apply` of the Apprise objects. Staging is a mutable test bed
  (ADR-037; the ArgoCD `kubelab-staging` app runs `selfHeal: false`), so a feature-branch service is
  applied directly rather than merged to `master` first. ArgoCD will show the resource OutOfSync
  until the branch merges — expected, harmless.

## Acceptance criteria

- [x] **#1 — Apprise live in staging; a message sent through it is delivered.** In-cluster `curl` to
  Telegram on 2026-06-14 (below). Re-measured 2026-10-10 through the webhook: Apprise answered 2xx for
  both tiers (a non-2xx makes n8n's HTTP node fail and the webhook answer 5xx), and the operator
  confirmed both messages in Slack. Channel superseded in writing: ADR-044, NOTIFY-002 addendum.
- [x] **#2 — `POST /webhook/notify` routes `page` and `log` to separate channels.** 2026-10-10:
  page 200 and log 200; the operator confirmed `page` in `#alerts` and `log` in `#ops-log`. The
  2026-06-16 run proved the same split on Telegram.
- [x] **#3 — hermes-nan `watchdog-down` routes through n8n.** Dispositioned, not met as written:
  hermes-nan is retired. `backup-fail` met by a different mechanism, `watchdog-down` ticketed
  (kubelab#2175). Evidence in the criterion #3 section below.
- [x] **#4 — a POST with a missing or a wrong shared secret is rejected.** 2026-10-10: no header 403,
  wrong `Bearer` value 403. Until today only the missing-header half was probed (see that section).

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

## Evidence — criteria #1, #2 and #4, re-measured (2026-10-10)

The spec sat unarchived for four months, so the evidence above was re-measured before archiving.
`make notify-smoke ENV=staging` at 2026-10-10T08:56Z, from branch `fix/notify-smoke-wrong-secret`:

```
Webhook: https://n8n.staging.kubelab.live/webhook/notify
  page (authenticated): HTTP 200 (expected 200) -> ok
  log (authenticated): HTTP 200 (expected 200) -> ok
  unauthenticated reject: HTTP 403 (expected 403) -> ok
  wrong secret reject: HTTP 403 (expected 403) -> ok
notify-smoke passed
```

The operator confirmed both messages in Slack: `page` in `#alerts`, `log` in `#ops-log`.

**Criterion #4 was half proven for four months.** It reads "missing/with a wrong shared secret". The
smoke ticked green on 2026-06-16 sent only a POST with no header, which a gate that checks the
header's presence refuses too. The fourth probe is new in this change: a random `Bearer` value per
run, never printed. `tests/test_notify_smoke.py` runs the smoke against a fake webhook that accepts
any header value and expects it to fail, and `make mutate` went red when the wrong probe was made to
send the real secret. Lesson-549 records it.

## Evidence — criterion #3 (2026-10-10)

The criterion's subject no longer exists. hermes-nan was retired on 2026-09-30, and AI-009
(`specs/AI-009-hermes-ace2/proposal.md`, ADR-068) moved its jobs to `hermes-kubelab` on ace2. The
two events the criterion names, judged separately:

- **`backup-fail`: met by a different mechanism.** Node backups are `node_backup` systemd units, and
  each one carries `OnFailure=kubelab-notify@%n.service`. That unit posts the journal tail to prod
  `/webhook/notify`, which is this fabric (ANSIBLE-035; `tests/test_node_notify_role.py` fails if the
  linkage is removed). Measured live: on 2026-10-07 02:47 rpi4's `node-backup-capture.service` timed
  out, and the failure reached Slack through this path with its journal excerpt.
- **`watchdog-down`: no successor.** Nothing watches the hermes-kubelab gateway. `monitors.json` holds
  three ace2 monitors (Tailscale ping, Open WebUI `/health`, backup push), and no gateway unit in
  `agent_stack` carries `OnFailure=`. The API is bound to `127.0.0.1:8642`, so a Kuma HTTP probe cannot
  reach it. Ticketed as kubelab#2175 (AI-013), which frames the decision.

## Notes / follow-ups

Historical (2026-06-14). Resolved since: Option B was built, the shared secret is in place, and the
next steps below were done.

- Deferred to the n8n-workflow stage: the routing decision **Option A (n8n holds URLs, stateless Apprise)
  vs Option B (Apprise tag→URL config from SOPS)** — ADR-044 points to B. The MVP manifest is
  compatible with both; B adds a mounted config + `chat_log`/`chat_notice` tiers.
- The webhook shared-secret/HMAC (criterion #4) gates exposing the endpoint to real sources.
- `toolkit` coupling (per-service hardcoded `SECRET_CATALOG`/`DEFINITIONS`/`IMAGE_SOURCES`) noted as a
  future refactor candidate — derive registries from `common.yaml` SSOT.

## Adversarial review findings

Filled after `dotf spec review NOTIFY-001`.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/identity-secrets/lesson-550-an-auth-smoke-that-only-omits-the-credential-cannot-tell-a-value-check-from-a-presence-check.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: ADR-044 and its NOTIFY-002 addendum already record the fabric and the channel change.
- [x] New pattern candidate for `00_meta/patterns/`? no: the rule is in the lesson, and it is specific to how this repo's smokes probe auth.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/NOTIFY-001/` -> `specs/archive/NOTIFY-001/`
- [x] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018): knowledge#90 is closed.
- [x] Promotions above executed (if any)
