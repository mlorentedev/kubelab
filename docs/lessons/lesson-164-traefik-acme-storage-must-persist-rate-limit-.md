---
id: lesson-164-traefik-acme-storage-must-persist-rate-limit-
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, traefik, acme, tls, k3s, letsencrypt]
---

# Traefik ACME storage MUST persist — rate limit disaster

**Context:** During prod cutover, Traefik pod was restarted multiple times (port changes, HelmChartConfig updates). Each restart lost acme.json and requested new certificates from Let's Encrypt.

**Problem:** K3s Traefik Helm chart uses `emptyDir` by default for `/data`. Every pod restart = fresh acme.json = new certificate requests. Let's Encrypt rate limits to 5 certificates per identical domain set per 168 hours. After 5+ restarts → all certificate requests denied → self-signed certs served → browser warnings on production.

**Solution:** Add `persistence.enabled: true` to HelmChartConfig:
```yaml
persistence:
  enabled: true
  storageClass: local-path
  size: 128Mi
```

**Rule:** NEVER deploy Traefik to production without ACME persistence. This should be part of the k3s_server role defaults, not an afterthought. Applied to both staging and prod.
**Tags:** `#traefik` `#acme` `#tls` `#k3s` `#letsencrypt`
