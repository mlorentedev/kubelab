---
id: lesson-557-hermes-reads-an-anthropic-key-prefix-as-oauth
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, agents, anthropic, auth]
---

# Hermes reads a new Anthropic key prefix as an OAuth token

**Context**: AI-012 PR 2 gave hermes-kubelab an Anthropic Haiku fallback. The
key came from the console with the prefix `sk-ant-usr`, and the console offers
no choice of format.

**Problem**: With NaN's key forced invalid, Hermes swapped to the fallback as
designed, and the fallback failed with "credit balance too low". The account
had credit. Hermes v2026.9.24 picks the auth style from the key's prefix:
`_is_oauth_token` (`agent/anthropic_credentials.py`) returns true for every
`sk-ant-*` that does not start with `sk-ant-api`. So it sent the key as a
Bearer token with Claude Code's identity headers, and the API refused it with a
billing message. The same key with `x-api-key` returned 200, from the
workstation and from inside the gateway container. Upstream `main` keeps the
same check. The refusal depends on the account: where the Claude Code identity
has credit to draw on (a subscription's API credit, say), the same request
succeeds and bills under that identity with no error, which is how upstream
#133856 was first reported. Both outcomes are the same defect, and the silent
one is worse. No setting selects the auth style for `api.anthropic.com`.

**Solution**: None in config. Upstream tracks it as NousResearch/hermes-agent
#133856 (P1), with fix PRs open. The fallback PR stays a draft (#2204) until a
pinned Hermes release carries the fix, and ace2 runs without a fallback. A proxy whose
`base_url` lies outside `anthropic.com` would force `x-api-key`, but it adds a
component to work around one function.

**Rule**: When a provider error contradicts what the account shows, replay the
same credential with a minimal direct request before you believe the message.
A client that infers auth from a key's shape fails on the next key format, and
the provider then reports the wrong cause.

**Tags**: `#hermes` `#anthropic` `#auth` `#spec-ai-012`
