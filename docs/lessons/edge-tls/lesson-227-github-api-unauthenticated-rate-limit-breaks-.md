---
id: lesson-227-github-api-unauthenticated-rate-limit-breaks-
type: lesson
status: active
created: "2026-03-27"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# GitHub API unauthenticated rate limit breaks Homepage widgets

**Context:** Homepage dashboard GitHub repo widgets showing API error
**Problem:** 3 GitHub API widgets at 60s refresh = 180 req/h. Unauthenticated limit is 60 req/h. Widgets show "API rate limit exceeded" error.
**Solution:** Increased refreshInterval to 300s (5 min) = 36 req/h. Long-term: add GitHub PAT to SOPS and pass as Authorization header in widget config.
**Tags:** `#dashboard` `#github` `#rate-limit`
