---
id: lesson-114-headscale-v0-28-has-no-http-health-endpoint
type: lesson
status: active
created: "2026-03-15"
owner: manu
tags: [kubelab, lesson, ansible, headscale, healthcheck, docker]
---

# Headscale v0.28 has no HTTP /health endpoint

**Context:** Implementing Ansible health check for Headscale role (ADR-020 Phase 2)
**Problem:** Ansible uri module checking http://127.0.0.1:8080/health returned 404. The Headscale container's own Docker healthcheck uses `headscale version` (CLI), not HTTP. There is no HTTP health endpoint in Headscale v0.28.
**Solution:** Use `docker inspect --format '{{.State.Health.Status}}' headscale` to check container health status instead of HTTP endpoint. The docker-compose healthcheck already verifies Headscale is working via CLI.
**Tags:** `#ansible` `#headscale` `#healthcheck` `#docker`
