---
id: lesson-138-always-validate-security-policies-in-staging-
type: lesson
status: active
created: "2026-03-20"
owner: manu
tags: [kubelab, lesson, security, authelia, staging, process]
---

# Always validate security policies in staging before prod cutover

**Context:** Phase 2 VPS K3s migration — changing Authelia access_control policies for gitea and minio
**Problem:** Applied security policy changes directly to prod overlay without testing in staging first. Could have broken login flows or locked out services.
**Solution:** Policy changes must follow staging → prod flow. HTTP status codes (200/302) are not enough — functional validation (UI loads, login works, data visible) is required before cutover.
**Tags:** `#security` `#authelia` `#staging` `#process`
