---
id: lesson-720-a-gotcha-nobody-re-measures-becomes-work
type: lesson
status: active
created: "2026-11-06"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, headscale]
---

# A gotcha nobody re-measures turns into work against a defect that does not exist

**Context**: #3010 asked to remove every `/health` probe on Headscale, because `CLAUDE.md`, lesson-114 and the setup runbook all said v0.28 has no such endpoint. The ticket itself noted the absence came from those documents, not from a probe.

**Problem**: One curl refuted it: `https://vpn.kubelab.live/health` answered `200 {"status":"pass"}` with `application/health+json`, Headscale's own handler (the errors service's `/health` answers plain `OK`). The prod e2e suite had been probing that path on every run and passing. The claim had a real cost besides the ticket: the container healthcheck was chosen as `headscale version` because of it, and that check passes with the server down (#3164).

**Solution**: Corrected the runbook and lesson-114; the platform manifest reads `health_path` like its siblings; the e2e expectation now asserts the `status` key, so the endpoint's format is checked on every prod run (#3010).

**Rule**: Before working a ticket whose premise is a documented absence ("X has no Y"), measure it once. Absences are the claims that age worst, because nothing exercises them: an endpoint that appears in a new version produces no error to notice.

**Tags**: `#headscale` `#healthcheck` `#pr-3010`
