---
id: lesson-285-notification-routing-converge-the-brain-speci
type: lesson
status: active
created: "2026-06-13"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Notification routing: converge the brain, specialize the egress

**Context:** NOTIFY-001 architecture session — unifying scattered alerts/notifications (Telegram/Discord/Slack/CI/webhooks) for a solo operator who also wants the design productizable for clients.
**Problem:** Notifications scattered with no routing logic; the instinct is to either collapse everything to one channel (loses platform strengths) or adopt a heavy notification product (Novu). Also conflating one-way event routing with two-way human communication, which is the real source of the perceived chaos.
**Solution:** Separate one-way event-routing (automated, this fabric) from two-way human-comms (channel strategy — NOT routed). Converge routing to one ingress/brain by REUSING the already-running n8n; specialize egress per platform via Apprise URLs; the declarative routing-table is the productizable unit (client deploy = swap config). Adopt-vs-build flips to ADOPT when the asset already exists (inverse of ADR-005's build decision — same constraint logic, opposite answer because n8n is already deployed and the gap is cross-cutting, not single-source). Heavy notification products (Novu) only earn their place at end-user scale (preference center / in-app inbox) and attach as a delivery SINK behind n8n, never a replacement — so the low-regret choice stays forward-compatible. Caveat: n8n workflows live in n8n's DB, so true IaC needs export/import of workflow JSON; Argo carries the stateless delivery infra but not the workflow content.
**Tags:** `#architecture` `#notifications` `#n8n` `#apprise` `#homelab` `#adopt-vs-build`
