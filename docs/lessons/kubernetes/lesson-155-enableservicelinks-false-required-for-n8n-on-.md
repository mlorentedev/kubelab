---
id: lesson-155-enableservicelinks-false-required-for-n8n-on-
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# enableServiceLinks: false required for n8n on K8s

**Context:** n8n pod in K8s kept falling back to basic_auth mode despite proper configuration.

**Problem:** K8s injects `N8N_PORT=tcp://10.43.x.x:5678` (Service env var) into pods. n8n tries to parse this as a port number, fails, and falls back to broken defaults including basic_auth. Same root cause as the Authelia `AUTHELIA_PORT` issue.

**Solution:** Set `enableServiceLinks: false` in n8n Deployment spec. This prevents K8s from injecting service-derived environment variables that collide with application config.

**Rule:** Any application that uses `<APP>_PORT` as a config key needs `enableServiceLinks: false` in K8s. Check for this pattern in ALL new service deployments. Known affected: Authelia, n8n.
**Tags:** `#k8s` `#n8n` `#debugging` `#enableServiceLinks`
