---
id: adr-044-unified-notification-routing-fabric
type: adr
status: accepted
created: "2026-06-14"
owner: manu
tags: [architecture, notifications, alerting, n8n, apprise, traefik, sops, redis, productization]
depends_on: [adr-037-environment-promotion-strategy, adr-038-secret-delivery-paths]
---

# ADR-044: Unified notification & alert routing fabric (n8n + Apprise)

> **Status:** Accepted
> **Date:** 2026-06-14
> **Related:** ADR-016 (Authelia auth tiers — the webhook ingress), ADR-026 (n8n workflows-as-code gap; APP-CONFIG-003), ADR-023 (Observability phase — Alertmanager as a future source), ADR-038 (SOPS secret delivery)
> **Ticket:** NOTIFY-001 — `mlorentedev/knowledge#90`. Consumers: SH-001 `#66`, SH-002 `#67`.
> **Origin:** `/architecture-session` (2026-06-14). Decision logic mirrors `knowledge` vault ADR-005 (hermes-nan monitoring adopt-vs-build), applied inversely.

## Context

Notifications and alerts are scattered with no routing logic. Every emitter hard-codes its
own destination:

- **hermes-nan** crons each `deliver: telegram:<chat>` (health, watchdog, backup, consumption
  digest, curator).
- **GitHub Actions** already POSTs to n8n on Docker build (`ci-publish.yml`) — but ad-hoc.
- **Uptime Kuma** (RPi3) fires its own webhook notifications.
- **vault tooling** (SH-001 #66, SH-002 #67) is planned to report via n8n, nothing built.
- **human channels** are tangled with automated ones: Discord hosts the NaN community,
  Telegram hosts Hermes chat + technical groups, Slack receives webhooks — and client comms /
  bookings have no defined home.

Two concerns are conflated, which is the root of the perceived chaos:

1. **Event routing** (one-way, automated): alerts, CI, webhooks, "booking created" pings. The
   destination is fundamentally *configuration*, not architecture — "only the endpoint changes".
2. **Human communication** (two-way): client calls, advisories, community chat. This is **not
   routed**; it is channel strategy.

This ADR addresses **(1) only**, with an explicit **productization** goal: the fabric must be
replicable so that setting up a client's notification routing is a config swap, not a rebuild.

**Reality verified (2026-06-14), grounded in the kubelab stack:** n8n is live in the `kubelab`
namespace (`n8nio/n8n:2.12.3`), exposed via Traefik at `n8n.{staging,prod}.kubelab.live`, with
webhooks enabled and external inbound reachability. No router/notifier (ntfy/gotify/Apprise) is
deployed. Prometheus/Alertmanager are NOT deployed (ADR-023 later phase). Hard constraint:
**self-hosted, no paid SaaS.**

## Constraints

| # | Constraint | Origin |
|---|------------|--------|
| C1 | Single ingress / one routing brain; no source hard-codes a destination. | operator + scatter pain |
| C2 | Specialize egress by platform strength; do not collapse to one channel. | operator |
| C3 | Reuse existing infra; no new heavy/stateful service. | adopt-vs-build (vault ADR-005) + n8n exists |
| C4 | Severity-driven, anti-fatigue: PAGE low-volume, NOTICE batched, nothing push-spams. | NOTIFY-001 |
| C5 | Audience separation: ops / dev-CI / client / community must not bleed. | operator |
| C6 | Secrets/PII out of the declarative SSOT — tokens/chat-IDs via SOPS. | ADR-038 |
| C7 | IaC: routing table + n8n workflow exported to versioned files. | platform doctrine |

## Reference audit (Regla del 3)

The fabric must generalize across notification *sources* (and, for productization, across
*deployment instances*). Auditing ≥2 divergent sources avoids designing the router around the
loudest one (hermes→Telegram) and rewriting at the next source:

| Dimension | R1 · hermes-nan crons | R2 · GitHub Actions / webhooks | R3 · vault-validate (SH-001/002) |
|---|---|---|---|
| Cadence | continuous (10 min → daily) | per push / build | weekly |
| Severity mix | info → critical (watchdog/backup) | warn/error (red build) | info/warn |
| Current sink | Telegram (hard-coded `deliver:`) | n8n webhook (`ci-publish.yml`), ad-hoc | none (planned) |
| Delivery need | push for PAGE, digest for NOTICE | push on failure, log on success | digest |
| Auth to ingress | unattended POST | unattended POST (CI runner) | unattended POST |

**Divergence log.** Common across all three → template candidates: a normalized envelope, a
`{domain, severity}` routing key, severity tiers (page/notice/log), unattended POST. Unique →
NOT generalized: hermes' Telegram default (an artifact of hard-coding, removed by the fabric),
Uptime Kuma's own notification format (adapter, not core).

## Decision

Adopt a **templated routing fabric: n8n (brain) + Apprise (pluggable delivery) + declarative
`routing-table` (config)**. n8n is the routing brain (already running, C3); Apprise
(`caronc/apprise`, stateless) is the delivery abstraction where every destination is a URL
(`tgram://`, `slack://`, `discord://`, `mailto://`) — one call fans out; the routing table is
the productizable unit (client deploy = swap table + Apprise creds).

1. **Ingress contract.** Every automated source POSTs one normalized envelope to a single n8n
   webhook:

   ```json
   { "domain": "ops|dev|client|community",
     "severity": "page|notice|log",
     "title": "...", "body": "...",
     "source": "hermes-nan/watchdog" }
   ```

2. **Routing.** n8n maps `{domain, severity}` → Apprise tag(s). `page` delivers immediately;
   `notice` accumulates (Redis TTL keys, already running at `redis:6379`) and a daily n8n cron
   flushes a digest; `log` archives without push.

3. **Egress (Apprise).** Deploy `caronc/apprise` as a **cluster-internal, stateless** Deployment
   (`infra/k8s/base/services/apprise.yaml`, no IngressRoute — only n8n calls it at
   `http://apprise:<port>/notify`). Apprise URLs/creds live in **SOPS** under
   `apps.services.automation.apprise.*` (ADR-038, C6).

4. **Channel taxonomy** (one job per platform; reversible config, not architecture):

   | Platform | Single job |
   |----------|------------|
   | Telegram | personal + ops + PAGE to the operator |
   | Discord | NaN community (+ optional `#log` archive) |
   | Slack | dev/CI + webhooks (+ client collaboration if retained) |
   | Email + Google | client formal comms + booking notifications |

5. **Workflow as code (C7).** n8n stores workflows in its SQLite DB (ADR-026). The routing
   workflow rides on the already-planned **APP-CONFIG-003** (`n8n export` → Git); until that
   lands, export the workflow JSON into the repo manually. Argo carries the stateless Apprise
   service as pure GitOps; it does NOT carry n8n workflow *content*.

### Resolved design questions

| Question | Decision |
|---|---|
| Router tech | n8n — settled by reality (already deployed); Hermes-native would cover only one source. |
| Webhook auth | The ingress `/webhook/*` must bypass Authelia (ADR-016) — POSTers are unattended — or use a shared-secret/HMAC header. **First spec item; verify the IngressRoute.** |
| Drop a platform? | Deferred — once the spine exists, dropping Slack is a one-line routing-table change, not an architecture decision. |
| Env strategy | Build + validate on **staging** (mutable, ADR-037), then promote to prod (selfHeal). |
| Client notifications | Same fabric (client = recipient): n8n + Apprise. End-user-scale (preference center / inbox) is out of band — see Rejected/Novu. |

### Implementation sequencing

(1) Apprise Deployment + SOPS creds (staging) → (2) n8n routing workflow PAGE/LOG → (3) NOTICE
digest via Redis → (4) migrate sources (GitHub Actions envelope; hermes-nan crons — first verify
Hermes `deliver:` accepts a webhook, else a thin wrapper deployed via its apply loop; Uptime
Kuma; vault-validate SH-001/002) → (5) promote staging→prod. MVP ≈ 1 focused day.

## Rejected

- **Personal hard-wiring (n8n only, channels in the workflow)** — fastest, but not replicable
  (client = rebuild) and fails the productization goal.
- **Novu (self-hosted notification platform)** — heavy new stateful service (API + worker + web
  + MongoDB + Redis) vs C3; its differentiators (subscriber preference center, in-app inbox) are
  unused for operator→operator routing. **Reopen trigger:** a client (or own product) needs
  end-user-scale notifications with preferences/inbox — then attach Novu as a delivery *sink*
  behind n8n, never a replacement (the fabric stays forward-compatible).
- **Collapse to a single channel** — loses per-platform strengths (C2) and mixes audiences (C5).
- **Wait for Alertmanager (ADR-023 later phase)** — not deployed; Alertmanager handles
  metrics-based alerts and, when it lands, becomes another *source* posting the envelope. It does
  not route the event/webhook traffic this fabric covers.

## Consequences

- One ingress + one routing table collapses the scatter into a governable N→1→M shape; severity
  tiers kill alert fatigue.
- The `routing-table` is a sellable/replicable artifact — a client deployment is a config swap.
- All OSS, self-hosted, zero recurring cost; Apprise adds one stateless service to operate.
- Migrating hermes-nan off `deliver: telegram:` touches its IaC (cronjobs + apply loop) and is
  gated on the Hermes-webhook-deliver check.
- The human-channel taxonomy is recorded but intentionally left as reversible config; client
  tooling (CRM, scheduler, video) is out of scope — each becomes a future *source*.
