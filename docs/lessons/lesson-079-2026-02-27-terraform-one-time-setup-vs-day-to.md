---
id: lesson-079-2026-02-27-terraform-one-time-setup-vs-day-to
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-02-27 — Terraform: One-Time Setup vs Day-to-Day Automation Are Different Problems

**Context:** Completing PREP-001 (Terraform DNS automation for K3s migration).

**Problem:** Confused the import/bootstrap phase (inherently manual: API calls, record ID lookups, state imports) with the day-to-day operations (fully automated: edit JSON → plan → apply). Tried to make the one-time setup "automatable" which added no value since it runs once.

**Solution:** Accept that Terraform has two modes:
1. **Bootstrap** (one-time): manual imports, credential setup, zone ID discovery → requires human judgment
2. **Steady-state** (repeatable): edit `services.json` → `toolkit infra terraform plan` → `toolkit infra terraform apply` → fully automated via toolkit

**Rule:** Don't try to automate one-time setup operations. Spend automation effort on the operations that repeat (add service, change IP, toggle proxy). Document the bootstrap procedure in a runbook for disaster recovery.

---
