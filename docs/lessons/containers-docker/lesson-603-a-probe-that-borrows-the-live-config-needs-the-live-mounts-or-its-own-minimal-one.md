---
id: lesson-603-a-probe-that-borrows-the-live-config-needs-the-live-mounts-or-its-own-minimal-one
type: lesson
status: active
created: "2026-10-18"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, ai-012, ai-018]
---

# A throwaway gateway that mounts the live config fails for reasons the check never meant to test

**Context**: Codifying the Haiku fallback proof (AI-018, #2299) as a role task. The manual sequence of lesson-574 mounted the rendered `config.yaml` read-only into a gateway of its own, which had worked on 2026-10-15.

**Problem**: Five runs on ace2 answered `Hermes couldn't start the model connection: invalid_params` on every retry, with the live pool copy, with the sandbox socket and with `TERMINAL_ENV=local` ruled out one at a time. No log line named the cause. The config had since gained MCP servers, a persona, managed skills and docker-sandbox mounts, none of which the throwaway container has. The proof was failing for the probe's own setup, which is the opposite of a check that passes by construction, and just as useless. Once it ran, a second trap showed: the answer was `pong`, but `docker logs` held no `Fallback activated`, because the gateway writes that event to the log files under its `HERMES_HOME`, not to the container's stdout.

**Solution**: The probe renders a config of its own, the `model` and `fallback_providers` sections only (`hermes-fallback-probe-config.yaml.j2`), and a test fails if those two differ from the live template. It reads `docker logs` and `$HERMES_HOME/logs/*.log` together, and asserts `pong`, `Fallback activated`, `anthropic` and no Slack connection. It runs as `make provision NODE=ace2 ENV=prod TAGS=agent_stack EXTRA='agent_stack_fallback_probe=true'` and removes the container, which takes the streamed copy of `auth.json` with it. Measured: `ok=199 changed=0 failed=0`, and `changed=0` on the plain re-run.

**Rule**: A probe should carry the smallest config that contains the behaviour under test, plus a test that ties that slice to the live one; borrowing the whole live config couples the check to every mount it needs. And read the event where the program writes it: a green answer with the event absent from the log you are reading is not yet a proof.

**Tags**: `#hermes` `#verification` `#ai-018`
