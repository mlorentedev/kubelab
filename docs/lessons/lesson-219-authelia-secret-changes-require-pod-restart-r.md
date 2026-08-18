---
id: lesson-219-authelia-secret-changes-require-pod-restart-r
type: lesson
status: active
created: "2026-03-27"
owner: manu
tags: [kubelab, lesson, authelia, k8s, secrets, credentials, debugging]
---

# Authelia Secret changes require pod restart — RELIAB-002 only covers ConfigMaps

**Context:** After running credentials-generate to change the SSOT admin password, Authelia kept rejecting the new password.
**Problem:** RELIAB-002 (configMapGenerator hash suffix) auto-restarts pods when ConfigMaps change, but Authelia user passwords live in K8s Secrets (authelia-users, authelia-secrets). Secrets use fixed names — K8s updates content silently but pods don't restart. User sees "authentication failed" with correct new password because pod still has old hash in memory.
**Solution:** Manual `kubectl rollout restart deployment/authelia` + `make flush-sessions` to clear stale Redis sessions. Permanent fix: DEBT-006 (Secret hash annotation on deployment template) — when Secret content changes, annotation hash changes, triggering automatic rolling update.
**Tags:** `#authelia` `#k8s` `#secrets` `#credentials` `#debugging`
