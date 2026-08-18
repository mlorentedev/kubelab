---
id: lesson-149-web-service-domain-mismatch-staging-mlorente-
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, dns, ingressroute, mlorente, config]
---

# Web service domain mismatch: staging.mlorente.dev vs web.staging.kubelab.live

**Context:** Web service (mlorente.dev portfolio) not loading on staging K3s.

**Problem:** IngressRoute used `staging.mlorente.dev` but common.yaml had the domain configured as `web.staging.kubelab.live`. Config mismatch caused Traefik to not match the incoming Host header.

**Solution:** Fixed to use `staging.mlorente.dev` consistently — this is the correct domain (mlorente.dev is an independent brand, not a kubelab subdomain).

**Rule:** Web/portfolio uses `staging.mlorente.dev` (independent brand domain), not `*.kubelab.live`. Always verify IngressRoute Host matches the actual DNS record.
**Tags:** `#dns` `#ingressroute` `#mlorente` `#config`
