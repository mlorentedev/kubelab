---
id: lesson-167-post-mortem-prod-cutover-cert-loss-performanc
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# POST-MORTEM: Prod cutover — cert loss + performance degradation

**Severity:** High — production served self-signed certs + 5s page loads

**What happened:**
1. Multiple Traefik restarts during cutover (port changes, HelmChartConfig updates)
2. Each restart lost acme.json (emptyDir, no persistence)
3. Let's Encrypt rate limit hit (5 certs/168h per domain set)
4. Production served self-signed certificates
5. CrowdSec bouncer adding 1-1.5s latency per request (no decision caching)

**Root causes:**
- ACME storage not persistent (K3s default: emptyDir)
- No pre-cutover checklist verifying TLS persistence
- CrowdSec bouncer queries LAPI per-request instead of caching
- Staging didn't catch it because we never restarted Traefik multiple times in staging

**What we should have done:**
1. Verify ACME persistence BEFORE first restart in prod
2. Use Let's Encrypt staging server (`acme-staging-v02`) for testing
3. Stress-test staging: restart Traefik 3+ times, verify certs persist
4. Benchmark response times in staging before declaring cutover-ready
5. Have a pre-cutover checklist (runbook)

**Fixes applied:**
- `persistence.enabled: true` in HelmChartConfig (both envs)
- CLAUDE.md gotcha added

**Fixes needed (next session):**
- CrowdSec bouncer caching (performance)
- Pre-cutover checklist (runbook)
- Let's Encrypt staging server for staging env
- Chaos test: automated Traefik restart + cert verification

**Rule:** Staging only protects you if you replicate prod OPERATIONS, not just deployments. Simulate restarts, reconfigs, and failure scenarios before cutover.
**Tags:** `#postmortem` `#traefik` `#acme` `#crowdsec` `#performance` `#cutover`
