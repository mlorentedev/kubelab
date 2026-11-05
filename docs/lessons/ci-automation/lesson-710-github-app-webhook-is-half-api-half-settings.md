---
id: lesson-710-github-app-webhook-is-half-api-half-settings
type: lesson
status: active
created: "2026-11-05"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-app, webhooks, console]
---

# A GitHub App's webhook is half API and half settings page, and an App created without one answers 404

**Context**: Registering the `kubelab-console` App's webhook as code (CONSOLE-004), with `PATCH /app/hook/config` authenticated by the App's own JWT.

**Problem**: The first plan run got `404` from `GET /app/hook/config`. The JWT was valid: `GET /app` answered 200 with the same token. The App had been created with webhooks off, and GitHub then has no hook config at all. It does not return an empty one. `GET /app` also showed `events: []`. The API can set the delivery config (URL, content type, TLS check, secret), but not the event subscriptions or the hook's Active toggle, which exist only in the App's settings page.

**Solution**: `make forge-github-hook` (`toolkit/features/github_app_hook.py`) converges what the API can set and checks the rest.
- It reads `events` from `GET /app` and reports a missing one (`issues`, `pull_request`) as the operator's step, exiting 2.
- It turns the 404 into the instruction: tick Active, enter the URL it prints, leave the secret empty and save, then run `APPLY=1`, which writes the secret.
- GitHub never returns the secret, so the read-back compares only the visible fields. `SECRET=1` resends the secret after a rotation.

**Rule**: For a GitHub App, `/app/hook/config` is reachable only once the hook has been activated in the settings page, and events are always a manual setting. Code the part the API exposes, and check the manual part with a read, so the step a human owns is still verified by a machine.

**Tags**: `#github-app` `#webhooks` `#console-004`
