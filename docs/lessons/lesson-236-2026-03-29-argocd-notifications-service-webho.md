---
id: lesson-236-2026-03-29-argocd-notifications-service-webho
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-29: ArgoCD notifications — service.webhook not service.slack for incoming webhooks

**Symptom:** `invalid_auth` then `notification service 'webhook' is not supported`.

**Root cause:** Three separate issues:
1. `service.slack` needs a Slack Bot Token (`xoxb-...`), not a webhook URL. For incoming webhooks use `service.webhook.<name>`.
2. Recipients for webhook are just `<name>`, not `webhook:<name>`.
3. Templates use `webhook: <name>:` block, not `slack:` block.

**Correct config:**
```yaml
notifiers:
  service.webhook.slack: |
    url: $slack-webhook-url
templates:
  template.example: |
    webhook:
      slack:
        method: POST
        body: '{"text": "message"}'
subscriptions:
  - recipients: [slack]
```

**Always check Context7 docs for ArgoCD notification config — the patterns are non-obvious.**
