---
id: lesson-526-hermes-docker-backend-applies-only-the-deny-list
type: lesson
status: active
created: "2026-10-06"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, agents, approvals, sandbox]
---

# Hermes's docker backend applies only `approvals.deny`, and nothing fails when that list is empty

**Context**: AI-009 PR 3a put hermes-kubelab (v2026.9.24) on ace2. ADR-068 D2
asks for three guards: commands run in a docker sandbox, approvals are
`manual` with a 300 s timeout, and a deny list carries over hermes-nan's
guardrails. The pinned source was read, and each claim was run through the
image's own evaluator, `hermes approvals test`.

**Problem**: The three guards are less than they look.

1. With no host path mounted into the sandbox, the docker backend counts as
   isolated and skips every command guard, the hardline floor and the manual
   prompts included (`tools/approval.py`, `_should_skip_container_guards`).
   `approvals.mode: manual` prompts for nothing the sandbox runs. Only
   `approvals.deny` is still applied.
2. `approvals.deny` entries are fnmatch globs, matched against the whole
   command, lowercased (`tools/approval_floors.py`). hermes-nan's guardrails
   file is regex. Copied verbatim, it would have blocked nothing.
3. When Hermes cannot load its config, it logs `Failed to load approval config`
   and carries on with an empty list. Measured with a data dir the image's user
   could not write: every one of 13 commands the list must refuse came back
   `allow`.
4. At every start, the image hands `$HERMES_HOME/config.yaml` to its runtime
   user (`chown`, `chmod 640`, `stage2-hook.sh`) and runs a migration that may
   rewrite it. A config file in the data dir belongs to the agent, approvals
   included, and it drifts from the role that rendered it.

**Solution**: The deny list was converted to globs. Each rule carries the
commands it must block and the commands it must allow (`tests/test_hermes_config.py`
runs them through Hermes's own match). The config is rendered outside the data
dir and mounted read-only over `config.yaml`. Every provision then reads the
list back through the running gateway: `docker exec -u hermes hermes-kubelab
hermes approvals test --env-type docker --json -- <cmd>`, which must return
`user-deny` for one command of each rule and `allow` for each allowed command
(`roles/agent_stack/tasks/hermes.yml`).

**Rule**: When a guard can fail open, read it back through the component that
enforces it, as that component's user, after every start. A rendered file and a
passing unit test show what was written, not what is applied. Before porting a
pattern list between tools, check which matcher the target uses.

**Tags**: `#hermes` `#ai-009` `#approvals`
