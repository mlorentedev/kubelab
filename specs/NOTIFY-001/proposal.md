---
id: "NOTIFY-001"
type: spec
status: draft
created: "2026-06-14"
issue: "mlorentedev/knowledge#90"
tags: [spec, proposal, notifications, n8n, apprise, kubelab]
template_version: "1.0"
---

# NOTIFY-001: Unified notification routing fabric (MVP, staging-first)

<!-- from issue mlorentedev/knowledge#90: NOTIFY-001 — Unified multi-channel notification/alert routing -->

## Why

Notifications are scattered with no routing logic — every emitter hard-codes its destination
(hermes-nan → Telegram, GitHub Actions → n8n ad-hoc, Uptime Kuma → its own webhook), so signal
is easy to miss and there is no replicable offering. ADR-044 decided the fabric: **n8n (brain) +
Apprise (pluggable delivery) + a declarative routing table**. This spec is the **MVP slice** that
proves the spine end-to-end on staging before fanning out. If we don't ship it, alert fatigue and
missed critical signals persist, and the productization goal stays theoretical.

## What

Staging-first MVP. Concrete outputs the system produces:

1. **Apprise** runs cluster-internal in the `kubelab` ns (no ingress); `POST http://apprise:<port>/notify`
   fans out to a channel.
2. **n8n** exposes `POST /webhook/notify` accepting the envelope
   `{domain, severity, title, body, source}`, validates a shared secret, and routes by
   `{domain, severity}` → Apprise tag(s): `page` (push), `log` (archive, no push).
3. **hermes-nan** `watchdog-down` and `backup-fail` events route **through n8n** (script `curl`s the
   envelope), not via the legacy `deliver: telegram:` path.

## Out of scope

- **NOTICE digest batching** (Redis TTL accumulation + daily flush) — phase 2.
- **Other sources** (full GitHub Actions migration, Uptime Kuma, vault-validate SH-001/002) — phase 3.
- **Prod promotion + n8n workflow GitOps** (APP-CONFIG-003 export→Git) — after the staging proof.

## Risks / open questions

- **[RESOLVED]** Hermes `--deliver` has no webhook target (only origin/local/telegram/discord/signal/
  platform:chat_id). → Use the `--no-agent --script` pattern: the cron's script `curl`s n8n itself
  (stdout silent). Deploys via the existing hermes apply loop. **Not a blocker.**
- **[RESOLVED]** n8n staging IngressRoute middlewares = `secure-headers` + `crowdsec-bouncer`, **no
  Authelia** → the webhook is reachable unattended today. **Confirm the prod overlay does not add
  Authelia to the webhook path** (if UI auth is later wanted, split `/webhook/*` to its own route).
- **[OPEN — BLOCKS exposure]** Webhook authn: CrowdSec is bot-mitigation, not authn. Add a
  **shared-secret/HMAC header** check inside the n8n workflow so arbitrary POSTs are rejected.
  Must be in place before the endpoint carries real traffic.
- **[OPEN — non-blocking]** Pin the `caronc/apprise` image tag + confirm the API port (apprise-api
  default `8000`). Resolve at implementation.

## Acceptance criteria

- [ ] Apprise Deployment+Service live in staging `kubelab` ns; an in-cluster
      `curl http://apprise:<port>/notify` delivers a test message to Telegram.
- [ ] `POST /webhook/notify` with `{domain:"ops",severity:"page",...}` → message in the Telegram
      PAGE channel; with `severity:"log"` → log channel, no push.
- [ ] hermes-nan `watchdog-down` (forced test) routes through n8n → Telegram, NOT via the old
      `deliver: telegram:` path; deployed via the apply loop (no hand-patching the box).
- [ ] A POST missing/with a wrong shared secret is rejected by the workflow.

## References

- ADR: `docs/adr/adr-044-unified-notification-routing-fabric.md`
- Issue: `mlorentedev/knowledge#90` (NOTIFY-001); consumers SH-001 `#66`, SH-002 `#67`
- Existing: `infra/k8s/base/services/n8n.yaml` (IngressRoute template), `infra/k8s/base/services/redis.yaml`,
  `.github/workflows/ci-publish.yml` (GH Actions→n8n pattern), SOPS `infra/config/secrets/staging.enc.yaml`
- Lesson: vault `kubelab/90-lessons.md` — "converge the brain, specialize the egress"
