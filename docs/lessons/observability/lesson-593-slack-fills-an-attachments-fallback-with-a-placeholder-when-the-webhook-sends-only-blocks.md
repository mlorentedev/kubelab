---
id: lesson-593-slack-fills-an-attachments-fallback-with-a-placeholder-when-the-webhook-sends-only-blocks
type: lesson
status: active
title: "Slack fills an attachment's fallback with a placeholder when the webhook sends only blocks"
created: "2026-10-18"
owner: manu
category: observability
tags: [kubelab, observability, slack, hermes, argocd]
---

# Slack fills an attachment's fallback with a placeholder when the webhook sends only blocks

**Context**: the hourly `kubelab:alert-triage` job reads the alert channels with `alert-activity.py` and hands the text to the agent.

**Problem**: Argo CD's notifications post Block Kit attachments (a header, a section with fields, a context link) and no `text`, `title` or attachment `text`. Slack then sets the attachment's `fallback` to the literal `[no preview available]`. The script preferred `fallback` over blocks, so the triage saw "no preview available" for every deploy and asked the operator what a healthy `Sync Succeeded` said (2026-10-17, `#deployments`).

**Solution**: `_text` reads the blocks of the message and of each attachment (header and section text, section fields, context elements) and uses `fallback` only when nothing else is there. `tests/test_hermes_alerts.py` carries the real shape and the last-resort case.

**Rule**: A chat API's summary field (`fallback`, `preview`) is written for notifications, not for readers, and can be a constant; read the structured content first and the summary last. Look at one raw message of each producer before writing the parser, as the shape differs per sender.

**Tags**: `#slack` `#hermes` `#argocd`
