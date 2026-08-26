---
id: lesson-389-a-declaration-with-no-readers-pays-its-whole-cost-at-once
type: lesson
status: active
created: "2026-08-24"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, ssot, gitea, ansible, health-check, issue-1389]
---

# A declaration with no readers costs nothing until the value matters, then breaks every copy at once

**Context**: Closing Gitea's anonymous surface (#1389). One flag, `REQUIRE_SIGNIN_VIEW: true`, took the container down and failed the provision in three different places.

**Problem**: `health_path: /api/healthz` had been declared in `common.yaml` since Gitea moved to the Beelink, and **nothing read it**. Meanwhile `/api/v1/version` was written out by hand in five live places — the compose healthcheck, two readiness probes in `gitea-bootstrap.sh`, the *Verify Gitea answers on its Tailscale address* task, and the `Wait for gitea to answer after restart` handler — plus a sixth copy in the e2e expectations.

While both endpoints answered anonymously, the divergence was **free and invisible**. Every copy worked, the declaration was ignored, and no test, lint or review could tell the difference. Then one flag made the two endpoints behave differently and all six failed in the same run: the container reported `unhealthy`, the verify task got 403, and the handler would have failed the moment it fired.

**The probes had been authenticating by not needing to.** Their correctness was a property of the system's permissiveness, not of the probes.

**Solution**: Every copy now resolves the declared value — `gitea_health_path` mapped from `common.yaml` in the playbook, and `$GITEA_HEALTH_PATH` for the bootstrap script, which lives in `files/` rather than `templates/` so it takes an env var instead of interpolation. A test asserts no live line in the role probes `/api/v1/version` again; prose may cite it, code may not.

**Rule**: A value declared in an SSOT and read by nothing is not a source of truth — it is a comment that happens to be well-formatted, and [lesson-380](../toolkit-tooling/lesson-380-the-catalog-names-every-consumer-and-nothing-acts-on-it.md) says the same about a catalog. This lesson adds the part that makes it urgent: **the cost is not paid gradually, it is paid all at once**, on the day something changes the governed value, and it lands on every copy simultaneously — which is precisely when you are already debugging something else. When you add a declaration, add its first reader in the same change; when you find one with no readers, treat it as an outage waiting for a trigger rather than as tidy-up. The tell is a config key you can delete without any test failing.

**Tags**: `#ssot` `#gitea` `#ansible` `#health-check` `#issue-1389`
