---
id: lesson-089-crowdsec-bouncer-lapi-registration-lost-after
type: lesson
status: active
created: "2026-03-01"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# CrowdSec Bouncer LAPI Registration Lost After Pod Recreation

**Context**: CrowdSec bouncer returning 403 for ALL requests on staging. `cscli bouncers list` showed zero registered bouncers despite `BOUNCER_KEY_crowdsec-bouncer` env var being correctly set.

**Problem**: CrowdSec's Docker image auto-registers bouncers from `BOUNCER_KEY_*` env vars via the entrypoint script — but only on **initial setup** (first run with empty config). When the pod was recreated (new image, config changes), the config PVC already had data from the previous run. The entrypoint detected "not a first run" and skipped bouncer registration, even though the DB PVC may have been fresh or the registration was lost.

**Impact**: Every request to api/web/blog returned 403 — the bouncer couldn't authenticate to the LAPI. The LAPI returned 403 to the bouncer's decision queries, and the bouncer fail-closed.

**Solution**: Manual registration with the existing API key:
```bash
kubectl exec -n kubelab deployment/crowdsec -- cscli bouncers add crowdsec-bouncer --key "$(kubectl get secret crowdsec-bouncer -n kubelab -o jsonpath='{.data.api-key}' | base64 -d)"
```
The registration is stored in the DB PVC and survives pod restarts.

**Rule**: After any CrowdSec pod recreation (deployment update, node migration, PVC issue), verify `cscli bouncers list` shows the registered bouncer. If empty, manually re-register with `cscli bouncers add --key`.

**Automated fix (2026-03-19)**: Added `postStart` lifecycle hook to CrowdSec deployment that waits for LAPI health then runs `cscli bouncers add --key ... || true`. Idempotent — succeeds on first run, no-ops if already registered. Manual intervention no longer needed.

---
