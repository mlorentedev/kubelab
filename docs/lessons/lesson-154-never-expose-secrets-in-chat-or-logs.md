---
id: lesson-154-never-expose-secrets-in-chat-or-logs
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, security, secrets, opsec]
---

# Never expose secrets in chat or logs

**Context:** Accidentally pasted Gitea admin credentials in plaintext during debugging.

**Rule:** Always reference secrets via `toolkit secrets show <path> --env <env>`, never paste values. Applies to: chat, commit messages, PR descriptions, log output.
**Tags:** `#security` `#secrets` `#opsec`
