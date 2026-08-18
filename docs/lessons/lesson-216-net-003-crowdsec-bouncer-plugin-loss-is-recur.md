---
id: lesson-216-net-003-crowdsec-bouncer-plugin-loss-is-recur
type: lesson
status: active
created: "2026-03-27"
owner: manu
tags: [kubelab, lesson]
---

# NET-003: CrowdSec Bouncer Plugin Loss is Recurrent

**What happened:** Traefik returned 404 for all routes using `crowdsec-bouncer` middleware. Logs showed `"plugin: unknown plugin type: bouncer"`. The HelmChartConfig on the cluster was missing the `experimental.plugins` section.

**Root cause:** The HelmChartConfig is managed by Ansible (`k3s_server` role template). If anything else modifies it (K3s upgrade, manual edit, or a generator that touches kube-system resources), the plugin registration is lost. Traefik restarts without the plugin → all middleware references fail → 404.

**Fix:** Always redeploy via `make deploy TARGET=k3s ENV=prod` to restore the full HelmChartConfig. Long-term: add a health check that verifies the plugin is registered (Traefik API `/api/plugins`).

**Pattern:** Critical Traefik plugins must be validated after any K3s/Traefik restart. If plugin is missing, all routes using that middleware fail silently (404, not 500).
