---
id: lesson-540-hermes-reuses-a-sandbox-and-dry-runs-a-command-without-looking-at-its-mounts
type: lesson
status: active
created: "2026-10-08"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, agents, approvals, sandbox]
---

# Hermes reuses a sandbox and dry-runs a command without looking at its mounts

**Context**: AI-009 PR 4 mounted the vault clone into hermes-kubelab's docker
sandbox (v2026.9.24): read-only, with the agent's zone writable inside it.
Before that PR the sandbox had no host path, and lesson-526 describes that
posture.

**Problem**: Two parts of Hermes decide things about a sandbox without reading
its mounts.

1. A persistent sandbox (`docker_persist_across_processes`, on by default) is
   found again by its labels: `hermes-agent=1`, the task id, the profile and an
   egress fingerprint (`tools/environments/docker.py`,
   `_attach_existing_container`). Volumes are not part of the match. A config
   that adds or removes a mount reaches no command until the old container is
   gone, and a restarted gateway does not remove it.
2. A host path in `terminal.docker_volumes` turns every command guard back on
   for the docker backend: the hardline floor, the dangerous-pattern prompts
   and `cron_mode` (`_should_skip_container_guards(env_type, has_host_access)`).
   The dry-run evaluator, `hermes approvals test --env-type docker`, calls the
   same function without `has_host_access`, so it always reports the posture
   without a mount. It measures the wrong path as soon as one exists.

**Solution**: The role removes every `label=hermes-agent=1` container on the
agent's daemon when the rendered config changed, after the gateway is
recreated. The read-back of the deny list evaluates with `--env-type local`
when the vault is mounted, which is the path the runtime takes, and accepts
`hardline-deny` as a refusal and `ask-approval` as a pass
(`roles/agent_stack/defaults/main.yml`, `_agent_stack_hermes_env_type`).

**Rule**: When a tool caches an environment, find out what its cache key is
before changing what the environment is made of. When a tool offers a dry run,
check which inputs of the real decision the dry run receives. A mount that
changes the decision and is absent from the dry run makes the dry run answer
a different question.

**Tags**: `#hermes` `#ai-009` `#approvals` `#sandbox`
