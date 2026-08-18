---
id: lesson-083-e2e-audit-api-health-endpoint-is-fully-mocked
type: lesson
status: active
created: "2026-02-28"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# E2E Audit: API /health Endpoint Is Fully Mocked

**Context**: E2E test suite writing API health structure tests. Inspected `healthchecks.go`.

**Problem**: All four health check functions (`checkDatabaseConnection`, `checkExternalServices`, `checkEmailConfiguration`, `checkRedisConnection`) are mocked — they always return `"healthy"` regardless of actual dependency state. The only real check is `checkEmailConfiguration` which validates non-empty config values, but doesn't actually test SMTP connectivity. Result: `/health` always returns `200 healthy` even if the database is unreachable or Redis is down.

**Solution**: Track as a backlog item. For now, E2E tests validate the JSON structure (correct keys, component names), not the accuracy of the health status. Real health checks should be implemented before production: actual DB ping, Redis ping, SMTP EHLO.

**Rule**: Health check endpoints MUST perform actual connectivity checks, not return hardcoded "healthy". A mocked health endpoint gives false confidence and defeats the purpose of readiness probes in K8s.

---
