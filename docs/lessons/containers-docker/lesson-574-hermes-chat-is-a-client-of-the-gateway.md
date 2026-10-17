---
id: lesson-574-hermes-chat-is-a-client-of-the-gateway
type: lesson
status: active
created: "2026-10-15"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, ai-012]
---

# In Hermes v0.22 `hermes chat` runs in the gateway, so a per-launch key or variable never reaches the model call

**Context**: Proving the Haiku fallback (AI-012 AC2) after moving hermes-kubelab to v0.22.1. The runbook forced NaN to fail with `docker exec -e NAN_API_KEY=sk-deliberately-invalid ... hermes chat -q ...`, which worked on v2026.9.24.

**Problem**: On v0.22.1 the same command, and `hermes chat --provider custom --api-key sk-deliberately-invalid ...`, both answered `pong` on NaN. The gateway's log shows `inbound message: platform=local`: the CLI hands the query to the running gateway, which holds its own environment, so nothing set on the `docker exec` reaches the provider call. A test that "passes" this way proves nothing: it never exercised the fallback. The same release removed the bundled tirith scanner and deletes `security.tirith_*` on upgrade, which the provision probe (it imported `tools.tirith_security`) would have failed on.

**Solution**: Fail the primary in a gateway of its own: run the pinned image on the agent's daemon with the live env file, `NAN_API_KEY` invalid, `SLACK_*` emptied and `API_SERVER_ENABLED=false` (a second Slack socket on the same app token would split the live bot's events), and its own `HERMES_HOME` with the rendered config mounted read-only. `docker exec ... hermes chat -q` against that container prints `Model fallback: ... using claude-haiku-5-5 via anthropic` and `pong`; the log has `Fallback activated`. Steps are in `docs/runbooks/hermes-kubelab.md` `## Models`.

**Rule**: When an image bump changes where a CLI runs its work, re-derive how each check forces its failure; a check whose injected fault cannot reach the code path is green by construction. Read the run's own log for the event you meant to cause (`Fallback activated`), not just the answer.

**Tags**: `#hermes` `#verification` `#ai-012`
