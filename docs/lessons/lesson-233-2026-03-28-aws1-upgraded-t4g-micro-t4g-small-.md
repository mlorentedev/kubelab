---
id: lesson-233-2026-03-28-aws1-upgraded-t4g-micro-t4g-small-
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-28: aws1 upgraded t4g.micro → t4g.small (+$3.14/mo) — eliminates all OOM issues

**Decision:** Upgrade aws1 from t4g.micro (1GB, ~$2.19/mo) to t4g.small (2GB, ~$5.33/mo). Delta: $3.14/mo.

**What it unblocks:**
- ApplicationSet controller re-enabled (ARGO-004)
- ArgoCD Notifications re-enabled (Slack/Telegram alerts)
- Image Updater (future — ARGO-004)
- Helm upgrades complete in ~2min without OOM
- Controller cold start ~2min vs 10-15min

**Resource budget (t4g.small, 2GB):**
- K3s + ArgoCD (7 pods): ~940MB
- Headroom: ~1GB (enough for Helm upgrades + node-exporter)

**Cost impact:** Cloud total: ~$18.39 → ~$21.53/mo
