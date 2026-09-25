---
id: lesson-458-a-gitea-pull-request-hook-also-delivers-comments
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, gitea, webhook, pr-agent]
---

# A Gitea hook subscribed to `pull_request` also delivers PR comments, and the narrow name is `pull_request_only`

**Context**: TOOL-080 declared the PR-Agent webhook with `events: [pull_request]`. The aim was to keep slash commands out, because the upstream Gitea server runs any comment starting with `/` from any author. The design was measured in a disposable local Gitea 1.25.5 lab (`specs/TOOL-080-forge-pr-reviewer/scope-lab.py`) before any code.

**Problem**: In Gitea's hook API, `pull_request` means *every* PR sub-event. `pullHook` in `routers/api/v1/utils/hook.go` ORs each sub-event with the presence of `pull_request`, so the hook stored all 8, `pull_request_comment` and `pull_request_review` included. PR comments are then delivered as `issue_comment`. In the lab, the PR author commented `/ask …` and the reviewer answered it with an LLM call. The declaration meant to exclude slash commands was the one that enabled them.

The reconciler's docstring already recorded the expansion (`webhook_changes`, measured 2026-09-04). It had been read as an ordering nuisance, not as a change in which events arrive.

**Solution**: Declare `[pull_request_only, pull_request_sync]`. That is opened, closed, reopened and edited, plus pushes. With it, the same lab delivered no comment event: `/ask` got no answer, and the reviewer made no API call. Gitea stores that pair back as `[pull_request, pull_request_sync]`, so the declared input name never reappears in the live list. A comparison for this hook must therefore be set equality against the stored names. A superset check never converges on `pull_request_only`, and it also misses a hook that was widened to include comments.

**Rule**: Before subscribing a hook to `pull_request`, ask whether the receiver acts on comments. Gitea's `pull_request` is a family, not an event. Where a surplus event is acted on rather than dropped, the subscription is part of the security boundary, and the reconciler must compare it for equality. Where the receiver fails closed, as n8n's workflow does, the superset rule stays fine.

**Tags**: `#gitea` `#webhook` `#tool-080` `#pr-agent`
