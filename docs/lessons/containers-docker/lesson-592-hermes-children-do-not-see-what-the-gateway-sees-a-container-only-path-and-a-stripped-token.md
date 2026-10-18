---
id: lesson-592-hermes-children-do-not-see-what-the-gateway-sees-a-container-only-path-and-a-stripped-token
type: lesson
status: active
title: "Hermes's children do not see what the gateway sees: a container-only path and a stripped token"
created: "2026-10-17"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, rootless-docker, slack]
---

# Hermes's children do not see what the gateway sees: a container-only path and a stripped token

**Context**: hermes-kubelab's gateway runs in a container; everything it spawns (the sandbox containers, the job scripts) is a child that sees a different world. Two defects with that one cause paged the operator about every hour from 2026-10-16.

**Problem**: (1) The managed skills were mounted into the gateway at `/managed-skills` and named in `skills.external_dirs`. Hermes passes each external dir to the sandbox as `docker run -v <dir>:...`, and the daemon that answers is the host's, so it looked for `/managed-skills` on the host and failed with `mkdir /managed-skills: permission denied`: exit 126, for every sandbox. `terminal`, `read_file`, `search_files` and `execute_code` all died, and so did every job that needs one. (2) `alert-activity.py` read `SLACK_BOT_TOKEN`; Hermes builds a job script's environment with `build_subprocess_env`, which always strips that name (`_ALWAYS_STRIP_FOLDED`, and `env_passthrough` cannot list it), so the script saw an empty string and the hourly triage reported "no Slack token" to `#agent-fleet` 24 times a day. Slack itself was healthy throughout: the messages were its output.

**Solution**: The skills mount path is the host path (`agent_stack_hermes_skills_mount: "{{ agent_stack_hermes_skills }}"`), the same convention as the vault and docs mirror. The env file carries the bot token a second time as `HERMES_ALERT_SLACK_TOKEN`, only when Slack and alert channels are configured, and the script reads that. Both were measured on ace2 before the change: a replay of the failing `docker run` with the host path listed `insights`; `build_subprocess_env` kept the new name and dropped `SLACK_BOT_TOKEN`. `tests/test_hermes_skills.py` and `tests/test_hermes_alerts.py` fail on either regression.

**Rule**: A path Hermes hands to the sandbox is a host path, and an environment variable a job script reads must survive `build_subprocess_env`; "it works in the gateway" proves neither. Prove a feature from the child's side (`docker run` it, spawn it) before calling it live: the skills were verified through `hermes skills list`, which runs in the gateway, and that is how a broken sandbox shipped. And a job that reports its own broken plumbing to an LLM every hour turns one fault into a flood; the cure is to fix the plumbing, and the question of paging once (#2423) is separate.

**Tags**: `#hermes` `#rootless-docker` `#slack`
