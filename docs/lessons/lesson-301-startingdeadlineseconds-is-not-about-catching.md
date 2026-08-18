---
id: lesson-301-startingdeadlineseconds-is-not-about-catching
type: lesson
status: active
created: "2026-08-09"
owner: manu
tags: [kubelab, lesson, kubernetes, cronjob, backup, kustomize, silent-failure, idp-032, gotcha]
---

# `startingDeadlineSeconds` is not about catching up a late run — it is what stops a CronJob from retiring itself (IDP-032)

**Context:** The prod PVC backup CronJob (`infra/k8s/overlays/prod/backup.yaml`, ADR-024) set `schedule`, `concurrencyPolicy: Forbid` and both history limits, but left `startingDeadlineSeconds` unset. A CKA-practices self-audit flagged it as a minor omission about missed-schedule catch-up.

**Problem:** The framing undersold it. Catch-up is the visible half: without the field, a run missed because the controller was down is skipped until tomorrow — annoying, survivable, and on a daily backup you would probably notice.

The invisible half is the one that bites. With the field unset, the CronJob controller counts missed schedules against an unbounded window. At **100** accumulated misses it stops scheduling the CronJob *permanently* and reports that only as an event on the object. Nothing crashes, no pod fails, no alert fires on a workload that simply never runs again. On an infrastructure whose homelab half is deliberately powered off between sessions, accumulating missed schedules is the normal operating mode, not an anomaly — so the counter is a live risk, not a theoretical one. The failure mode of a backup system is silence, and this one is silent by construction.

**Solution:** `startingDeadlineSeconds: 3600` on the CronJob spec. The value bounds the miss-counting window and lets a run missed at 03:00 still start by 04:00, which leaves the existing `activeDeadlineSeconds: 1800` room to finish inside the same maintenance window. The comment in the manifest records the reasoning, because the field reads like a nicety and the next person to touch it needs to know it is not.

Verification was the render, not the file: `kubectl kustomize infra/k8s/overlays/prod` confirms the field survives into the built manifest. Editing an overlay proves nothing on its own — a patch elsewhere in the overlay can strip a field silently, and the diff still looks correct.

**Rule:** For any scheduled workload, ask what happens after N consecutive misses, not just after one. Controllers that give up quietly are worse than controllers that fail loudly, and "the job did not run" produces no signal unless something is watching for absence. Corollary for Kustomize: the unit of verification is the **built output**, never the source file you edited.

**Tags:** `#kubernetes` `#cronjob` `#backup` `#kustomize` `#silent-failure` `#idp-032` `#gotcha`
