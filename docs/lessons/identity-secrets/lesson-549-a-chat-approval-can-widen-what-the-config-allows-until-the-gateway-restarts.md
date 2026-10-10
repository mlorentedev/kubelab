---
id: lesson-549-a-chat-approval-can-widen-what-the-config-allows-until-the-gateway-restarts
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, hermes, approvals, slack]
---

# A chat approval can widen what the config allows, until the gateway restarts

**Context**: Wiring hermes-kubelab's Slack gateway (spec AI-009 PR 3c). The
config that sets `approvals.mode: manual` is rendered by Ansible and mounted
read-only, so the agent cannot rewrite its own posture. The question was
whether anything said in chat can still change that posture.

**Problem**: Two chat actions can, and neither touches the file. Both were read
from the v2026.9.24 source, not measured:

- The **Always** button on an approval prompt calls `approve_permanent`, which
  adds the pattern to an in-memory set, and then `save_permanent_allowlist`,
  which writes `command_allowlist` into `config.yaml`. With the file read-only
  the write fails, and is only logged (`Could not save allowlist`). The pattern
  stays approved in memory until the process exits. "Always" means "until the
  next recreate", and no file records the grant.
- **`/yolo`** turns off approval prompts for one session
  (`enable_session_yolo`). No admin split is configured, so every allowlisted
  user can run it. The deny list and Hermes's hardline floor still apply under
  it, because the deny globs block even with approvals off.

**Solution**: Neither one is a defect for a single-operator gateway. Both are
the operator's own authority, and both are bounded by the process's lifetime.
They are recorded in the runbook so that a widened posture is never read off
the config. To return to the declared posture, recreate the gateway. A
provision whose config changed does that (`--force-recreate`), and so does
`docker compose ... up -d --force-recreate` run as the agent's user. Restricting
`/yolo` would take `allow_admin_from` plus `user_allowed_commands` in the
platform's `extra:` block. That is left for when a second Slack user is added.

**Rule**: A read-only config proves what the process loaded. It does not prove
what the process allows now. Before calling a posture enforced by a file, list
every runtime path that changes the same decision (buttons, slash commands, an
API), and say how long each one lasts.

**Tags**: `#hermes` `#approvals` `#slack` `#ai-009`
