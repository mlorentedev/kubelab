---
id: lesson-277-n8n-v2-blocks-env-in-expressions-by-default-u
type: lesson
status: active
created: "2026-06-14"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# n8n v2 blocks `$env` in expressions by default — use a native Header Auth credential for webhook secrets

**Context:** NOTIFY-001 criterion #4 needs the `/webhook/notify` ingress to reject unauthenticated POSTs. The instinct (pure IaC) was to keep the shared secret in SOPS, inject it as an env var into the n8n pod, and compare the inbound `Authorization` header against `$env.NOTIFY_SHARED_SECRET` in an IF node — so the auth logic lives in the exported workflow JSON.
**Problem:** The deployed n8n is `n8nio/n8n:2.12.3`, and **n8n v2 ships `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` by default** — `$env` is unavailable in expressions and Code nodes. Making the `$env` approach work would require flipping that flag to `false` on the Deployment, which re-opens environment-variable access to **every** workflow and Code node in the instance — the exact attack surface n8n v2 deliberately closed. A per-feature secret check would impose a cluster-wide security regression.
**Solution:** Use n8n's **native Header Auth credential** on the Webhook node: n8n rejects a missing/wrong header with 403 automatically (covers criterion #4 with zero custom logic) and the secret lives in n8n's encrypted credential store (`N8N_ENCRYPTION_KEY`), not an env var. Keep the canonical copy in SOPS (`apps.services.automation.notify.webhook_secret`) for recovery/rotation; the credential is created once via the UI by pasting that value. Trade-off accepted: the credential is not inside the exported workflow JSON (the JSON only references it), but that beats weakening the whole instance. Generalizes: prefer the platform's own credential primitive over `$env` for per-resource secrets; check the major-version security defaults before designing around env access.
**Tags:** `#n8n` `#notifications` `#notify-001` `#adr-044` `#security` `#webhooks` `#gotcha`
