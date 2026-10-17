---
id: lesson-120-traefik-api-insecure-false-disables-port-8080
type: lesson
status: active
created: "2026-03-15"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# Traefik api.insecure=false disables port 8080 dashboard access

**Context:** Migrating Traefik VPS config from manual to Ansible-templated
**Problem:** After templating traefik.yml with api.insecure: false, the dashboard became inaccessible on port 8080. The old config had insecure: false too but the dashboard was accessed directly. With the new config, the dashboard only works via the Traefik router (HTTPS on 443 with Host rule), which requires a valid TLS cert for the dashboard domain.
**Solution:** This is correct behavior — insecure: false means dashboard is only available through a proper router with TLS + auth. The ACME wildcard cert for *.kubelab.live covers traefik.kubelab.live. Dashboard now requires basicAuth credentials to access.
**Tags:** `#traefik` `#security` `#dashboard`
