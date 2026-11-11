---
id: lesson-114-headscale-v0-28-has-no-http-health-endpoint
type: lesson
status: active
created: "2026-03-15"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Headscale v0.28 does answer /health; this lesson first said it did not

**Correction (2026-11-06, #3010):** the original claim, kept below, is false. `https://vpn.kubelab.live/health` answers `{"status":"pass"}` with `application/health+json`, and the v0.28.0 docs list both `/health` and the `headscale health` command. The 404 recorded in March may well have happened; the conclusion drawn from one probe was wider than the probe. See lesson-720 for what the wrong claim cost.

**Context:** Implementing Ansible health check for Headscale role (ADR-020 Phase 2)

**Problem (original, wrong):** Ansible uri module checking http://127.0.0.1:8080/health returned 404. The Headscale container's own Docker healthcheck uses `headscale version` (CLI), not HTTP. There is no HTTP health endpoint in Headscale v0.28.

**Solution (original, superseded):** Use `docker inspect --format '{{.State.Health.Status}}' headscale` to check container health status instead of HTTP endpoint. That check was weak: `headscale version` exits 0 with the server down. Since #3164 the healthcheck runs `headscale health`, which asks the running server.

**Rule:** Probe Headscale's health at `/health` and check the media type, since the errors service also answers `/health`, in plain text.

**Tags:** `#ansible` `#headscale` `#healthcheck` `#docker`
